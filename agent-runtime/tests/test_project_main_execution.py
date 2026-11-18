import copy
from types import SimpleNamespace

import httpx
import pytest
from test_native_main import fixture_binding, stopped
from test_runtime import until
from test_swarm_provider_generations import prepared

from roami_agent.conversation.main_execution import main_binding
from roami_agent.executors.targets import TargetDirectory
from roami_agent.protocol.errors import DomainError
from roami_agent.server.http import create_app
from roami_agent.storage.database import row

pytest_plugins = ["test_project_main_wakeup"]


async def setup_main(fixture, monkeypatch):
    runtime, main = fixture
    calls = []
    proof = prepared("prepared-main", session="native-session")
    proof["sessionBinding"]["providerConversationId"] = "native-provider"

    async def workspace(self, project):
        assert project == "project"
        return {"directory": "/project"}

    async def command(sub, *args, **kwargs):
        calls.append((sub, args, kwargs))
        if sub == "prepared":
            return copy.deepcopy(proof)
        if sub == "launch":
            binding = {**fixture_binding(), "binding": proof["sessionBinding"]}
            return stopped(binding)
        raise AssertionError(sub)

    monkeypatch.setattr(TargetDirectory, "project_workspace", workspace)
    runtime.main_executions.executor = SimpleNamespace(command=command)
    spec = {
        "commandKey": "bind-main",
        "projectId": "project",
        "expectedGeneration": 0,
        "executor": "claude",
        "model": "free",
        "preparedLaunchKey": "prepared-main",
    }
    return runtime, main, spec, proof, calls


async def test_project_main_switch_keeps_original_identity_and_replays_receipt(
    wake_runtime, store, monkeypatch
):
    runtime, main, spec, _, calls = await setup_main(wake_runtime, monkeypatch)
    home = await runtime.conversations.main("alice")
    before = await runtime.conversations.messages("alice", main["id"])
    result = await runtime.main_executions.configure("alice", main["id"], spec)
    assert result == {
        "generation": 1,
        "executor": "claude",
        "model": "free",
        "conversationId": main["id"],
        "sessionId": "native-session",
        "projectId": "project",
    }
    assert await runtime.main_executions.configure("alice", main["id"], spec) == result
    assert len(calls) == 1
    assert (await runtime.conversations.messages("alice", main["id"]))["messages"] == before[
        "messages"
    ]
    assert (await runtime.conversations.main("alice"))["id"] == home["id"] != main["id"]
    binding = await store.call(lambda db: main_binding(db, "alice", main["id"]))
    assert binding["generation"] == 1 and binding["conversation_id"] == main["id"]
    with pytest.raises(DomainError, match="REQUEST_KEY_CONFLICT"):
        await runtime.main_executions.configure("alice", main["id"], {**spec, "model": "paid"})
    for turn in [
        {"owner_id": "alice", "conversation_id": home["id"]},
        {"owner_id": "bob", "conversation_id": main["id"]},
    ]:
        assert await runtime.main_executions.loop_for(runtime.loop, turn) is runtime.loop
    selected = await runtime.main_executions.loop_for(
        runtime.loop, {"owner_id": "alice", "conversation_id": main["id"], "id": "test"}
    )
    assert selected is not runtime.loop and selected.model.model == "free"
    assert (
        selected.preemptible is runtime.loop.preemptible
        and selected.turn_tasks is runtime.loop.turn_tasks
    )


async def test_actual_main_turn_uses_native_provider_and_original_reply_pipeline(
    wake_runtime, store, monkeypatch
):
    runtime, main, spec, _, calls = await setup_main(wake_runtime, monkeypatch)
    await runtime.main_executions.configure("alice", main["id"], spec)
    runtime.loop.require_final_tool = True
    await runtime.start()
    turn = await runtime.chat.submit(
        "alice", main["id"], "ask-main", "Coordinate the original team"
    )
    await until(
        store,
        lambda db: row(
            db, "SELECT id FROM turns WHERE id=? AND state='completed'", (turn["turnId"],)
        ),
    )
    messages = (await runtime.conversations.messages("alice", main["id"]))["messages"]
    assert messages[-1]["content"]["text"] == "Actual native answer"
    launches = [c for c in calls if c[0] == "launch"]
    assert len(launches) == 1
    assert launches[0][2]["spec"]["sessionId"] == "native-session"
    assert main["id"] in launches[0][2]["spec"]["prompt"]
    assert runtime.loop.model.model == "injected-model"


@pytest.mark.parametrize(
    "change", ["home", "other project", "busy", "generation", "wrong model", "wrong directory"]
)
async def test_main_binding_rejects_scope_and_unready_changes(wake_runtime, monkeypatch, change):
    runtime, main, spec, proof, _ = await setup_main(wake_runtime, monkeypatch)
    cid = main["id"]
    if change == "home":
        cid = (await runtime.conversations.main("alice"))["id"]
    elif change == "other project":
        spec["projectId"] = "other"
    elif change == "busy":
        await runtime.chat.submit("alice", cid, "pending", "Do work")
    elif change == "generation":
        spec["expectedGeneration"] = 1
    elif change == "wrong model":
        proof["configuredModel"] = "paid"
    elif change == "wrong directory":
        proof["workspace"]["directory"] = "/other"
    with pytest.raises(DomainError):
        await runtime.main_executions.configure("alice", cid, spec)
    assert await runtime.db.call(lambda db: main_binding(db, "alice", cid)) is None


async def test_main_execution_http_keeps_owner_and_project_boundaries(wake_runtime, monkeypatch):
    runtime, main, spec, _, _ = await setup_main(wake_runtime, monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        url = f"/v1/conversations/{main['id']}/execution"
        assert (await client.get(url)).json()["data"]["executor"] == "roami"
        response = await client.put(url, json=spec)
        assert response.status_code == 200, response.text
        assert response.json()["data"]["executor"] == "claude"
        assert (await client.put(url, json={**spec, "executor": "shell"})).status_code == 422
        assert (await client.get(url, headers={"X-Roami-Owner": "bob"})).status_code == 404


async def test_group_chat_reaches_same_bound_main_and_native_provider(
    wake_runtime, store, monkeypatch
):
    runtime, main, spec, _, calls = await setup_main(wake_runtime, monkeypatch)
    await runtime.main_executions.configure("alice", main["id"], spec)
    group = await runtime.swarms.create(
        "alice",
        {
            "commandKey": "group",
            "name": "Original team",
            "goal": "Coordinate original members",
            "mainConversationId": main["id"],
            "target": {"kind": "project", "projectId": "project"},
        },
    )
    await runtime.swarms.control(
        "alice",
        group["id"],
        {"commandKey": "pause", "expectedRevision": group["revision"], "action": "pause"},
    )
    runtime.loop.require_final_tool = True
    await runtime.start()
    delivery = await runtime.swarms.send(
        "alice",
        group["id"],
        {"commandKey": "group-message", "text": "@main Review our existing team"},
    )
    await until(
        store,
        lambda db: row(
            db,
            "SELECT id FROM turns WHERE id=? AND conversation_id=? AND state='completed'",
            (delivery["turnId"], main["id"]),
        ),
    )
    launches = [
        c
        for c in calls
        if c[0] == "launch"
        and c[2]["spec"]["key"].startswith("project-main:" + delivery["turnId"] + ":")
    ]
    assert len(launches) == 1 and launches[0][2]["spec"]["sessionId"] == "native-session"
    assert "@main Review our existing team" in launches[0][2]["spec"]["prompt"]
    assert (await runtime.swarms.snapshot("alice", group["id"], include_memory=False))[
        "mainConversationId"
    ] == main["id"]


async def test_native_provider_cannot_be_reused_by_another_project(wake_runtime, monkeypatch):
    runtime, main, spec, _, _ = await setup_main(wake_runtime, monkeypatch)
    await runtime.main_executions.configure("alice", main["id"], spec)
    other = await runtime.conversations.create("alice", project_id="other-project")

    async def workspace(self, project):
        return {"directory": "/project"}

    monkeypatch.setattr(TargetDirectory, "project_workspace", workspace)
    with pytest.raises(DomainError, match="SWARM_PROVIDER_ALREADY_BOUND"):
        await runtime.main_executions.configure(
            "alice",
            other["id"],
            {**spec, "commandKey": "other-binding", "projectId": "other-project"},
        )


async def test_project_model_commands_never_write_home_model_settings(wake_runtime, monkeypatch):
    runtime, main, spec, _, _ = await setup_main(wake_runtime, monkeypatch)
    await runtime.main_executions.configure("alice", main["id"], spec)
    writes = []

    async def save(owner, value):
        writes.append(value)
        return {"main": value["main"]}

    monkeypatch.setattr(runtime.model_settings, "save", save)
    for command in ["/model", "/model free", "/model roami-claude/free"]:
        result = await runtime.chat.submit("alice", main["id"], command, command)
        assert result == {
            "kind": "model",
            "model": "free",
            "executor": "claude",
            "conversationId": main["id"],
        }
    with pytest.raises(DomainError, match="PROJECT_MAIN_MODEL_CONFLICT"):
        await runtime.chat.submit("alice", main["id"], "other-model", "/model paid")
    with pytest.raises(DomainError, match="PROJECT_MAIN_NATIVE_COMMAND_REQUIRED"):
        await runtime.chat.submit("alice", main["id"], "compact", "/compact")
    status = await runtime.chat.status("alice", main["id"])
    assert status["model"] == "free" and status["executor"] == "claude"
    assert status["sessionId"] == "native-session" and not writes
    home = await runtime.conversations.main("alice")
    with pytest.raises(DomainError, match="MODEL_SETTINGS_FORBIDDEN"):
        await runtime.chat.submit("alice", home["id"], "home-model", "/model homepage-model")
    local_home = await runtime.conversations.main("local")
    await runtime.chat.submit("local", local_home["id"], "home-model", "/model homepage-model")
    assert writes == [{"main": {"model": "homepage-model", "reasoningEffort": None}}]


@pytest.mark.parametrize("scheduled", [False, True])
async def test_bound_main_admission_does_not_require_home_model(
    wake_runtime, monkeypatch, scheduled
):
    runtime, main, spec, _, _ = await setup_main(wake_runtime, monkeypatch)
    await runtime.main_executions.configure("alice", main["id"], spec)
    runtime.chat.model.model = ""
    result = (
        await runtime.chat.wake_project("alice", main["id"], "project", "wake", "Continue the team")
        if scheduled
        else await runtime.chat.submit("alice", main["id"], "direct", "Continue the team")
    )
    assert result["kind"] == "message"
