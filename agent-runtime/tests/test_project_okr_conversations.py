import asyncio
import json

import httpx
import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.conversation.project_okr import registered_project
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.tool_arguments import ToolArgumentsError
from roami_agent.server.http import create_app
from roami_agent.storage.database import row


@pytest.fixture
async def project_runtime(store, monkeypatch):
    calls = []
    state = {"workspace": None}

    async def execute(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[1:3] == ["project", "show"]:
            data = {"key": argv[3]}
        elif argv[3] == "show":
            data = state["workspace"]
        else:
            body = json.loads(kwargs["input_data"])
            if body["revision"] != (state["workspace"] or {}).get("revision", 0):
                return {"exitCode": 1, "stdout": '{"error":"OKR_CONFLICT"}'}
            data = {**body, "revision": body["revision"] + 1, "projectId": argv[4]}
            state["workspace"] = data
        return {"exitCode": 0, "stdout": json.dumps({"data": data})}

    monkeypatch.setattr("roami_agent.conversation.project_okr.execute", execute)
    runtime = Runtime(store, ConversationModel())
    try:
        yield runtime, calls, state
    finally:
        await runtime.close()


async def create_goal(runtime, project="registered", key="goal"):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        return await client.post(
            "/v1/conversations",
            json={"projectId": project, "title": "Goal discussion", "requestKey": key},
        )


async def test_goal_discussion_binds_registered_project_independently_and_idempotently(
    project_runtime, store
):
    runtime, calls, _ = project_runtime
    result = await create_goal(runtime)
    assert result.status_code == 201, result.text
    cid = result.json()["data"]["id"]
    assert cid != (await runtime.conversations.main("alice"))["id"]
    binding = await store.call(
        lambda db: row(
            db, "SELECT * FROM project_okr_conversations WHERE conversation_id=?", (cid,)
        )
    )
    assert binding["project_id"] == "registered" and binding["owner_id"] == "alice"
    assert (await create_goal(runtime)).json()["data"]["id"] == cid
    assert (await create_goal(runtime, project="another-project")).status_code == 409
    assert calls[0][0] == ["roami", "project", "show", "registered", "--json"]


async def test_bound_goal_tools_read_empty_goal_and_save_only_its_project(project_runtime):
    runtime, calls, _ = project_runtime
    cid = (await create_goal(runtime)).json()["data"]["id"]
    binding = {"owner": "alice", "conversation": cid, "role": "main"}
    read = runtime.tools.registry["project_okr_context"]
    update = runtime.tools.registry["project_okr_update"]
    assert await read.handler({}, binding) == {"projectId": "registered", "saved": False}
    body = {"revision": 0, "objective": "User confirmed", "keyResults": []}
    saved = await update.handler({"operation": "save", "payload": body}, binding)
    assert saved["revision"] == 1 and saved["projectId"] == "registered"
    assert calls[-1][0] == [
        "roami",
        "project",
        "okr",
        "save",
        "registered",
        "--file",
        "-",
        "--json",
    ]
    assert json.loads(calls[-1][1]["input_data"]) == body
    assert (await read.handler({}, binding))["objective"] == "User confirmed"
    with pytest.raises(DomainError, match="OKR_CONFLICT"):
        await update.handler({"operation": "save", "payload": body}, binding)
    with pytest.raises(ToolArgumentsError):
        update.validate({"operation": "save", "payload": body, "projectId": "another"})


async def test_goal_tools_reject_home_workers_and_other_owners_before_execution(project_runtime):
    runtime, calls, _ = project_runtime
    cid = (await create_goal(runtime)).json()["data"]["id"]
    home = (await runtime.conversations.main("alice"))["id"]
    read = runtime.tools.registry["project_okr_context"]
    count = len(calls)
    for binding in [
        {"owner": "alice", "conversation": home},
        {"owner": "alice", "conversation": cid, "taskId": "worker"},
        {"owner": "bob", "conversation": cid},
    ]:
        with pytest.raises(DomainError):
            await read.handler({}, binding)
    assert len(calls) == count


@pytest.mark.parametrize("pid", ["--server=https://unrelated", "", "bad\0project"])
async def test_goal_binding_rejects_option_like_project_ids_before_cli(project_runtime, pid):
    runtime, calls, _ = project_runtime
    with pytest.raises(DomainError, match="INVALID_OKR_PROJECT_ID"):
        await registered_project(runtime.settings, pid)
    assert not calls


async def test_reopening_and_concurrent_windows_share_one_project_main(project_runtime, store):
    runtime, _, _ = project_runtime
    replies = await asyncio.gather(*(create_goal(runtime, key=f"window-{n}") for n in range(12)))
    assert all(reply.status_code == 201 for reply in replies)
    ids = {reply.json()["data"]["id"] for reply in replies}
    assert len(ids) == 1
    assert (await create_goal(runtime, key="reopened")).json()["data"]["id"] in ids
    assert (
        await store.call(
            lambda db: db.execute("SELECT count(*) FROM project_okr_mains").fetchone()[0]
        )
        == 1
    )
    assert await store.call(lambda db: db.execute("SELECT count(*) FROM turns").fetchone()[0]) == 0


async def test_project_main_isolated_from_home_other_projects_and_other_owners(project_runtime):
    runtime, _, _ = project_runtime
    first = (await create_goal(runtime)).json()["data"]["id"]
    second = (await create_goal(runtime, project="another", key="another")).json()["data"]["id"]
    bob = await runtime.conversations.create("bob", project_id="registered")
    assert len({first, second, bob["id"], (await runtime.conversations.main("alice"))["id"]}) == 4
    assert (await runtime.conversations.main("bob"))["id"] != bob["id"]


@pytest.mark.parametrize("other_project", [False, True])
async def test_project_coordinator_cannot_save_another_teams_binding(
    project_runtime, other_project
):
    runtime, calls, _ = project_runtime
    cid = (await create_goal(runtime)).json()["data"]["id"]
    other = await runtime.conversations.create("alice", "Other leader")
    team = await runtime.swarms.create(
        "alice",
        {
            "name": "Other team",
            "goal": "A separate goal",
            "commandKey": "separate-team",
            "mainConversationId": other["id"],
            "target": {"kind": "project", "projectId": "other" if other_project else "registered"},
        },
    )
    before = len(calls)
    with pytest.raises(DomainError, match="PROJECT_OKR_TEAM_CONFLICT"):
        await runtime.tools.registry["project_okr_update"].handler(
            {"operation": "save", "payload": {"revision": 0, "swarm": team["id"]}},
            {"owner": "alice", "conversation": cid, "role": "main"},
        )
    assert len(calls) == before


async def test_existing_dedicated_swarm_main_is_adopted_without_recreating_team(
    project_runtime, store
):
    runtime, _, state = project_runtime
    await runtime.conversations.main("alice")
    leader = await runtime.conversations.create("alice", "Existing project leader")
    swarm = await runtime.swarms.create(
        "alice",
        {
            "name": "Existing team",
            "goal": "User goal",
            "commandKey": "existing",
            "mainConversationId": leader["id"],
            "target": {"kind": "project", "projectId": "registered"},
        },
    )
    state["workspace"] = {"swarm": swarm["id"]}
    before = await runtime.swarms.snapshot("alice", swarm["id"], include_memory=False)
    assert (await create_goal(runtime)).json()["data"]["id"] == leader["id"]
    assert await runtime.swarms.snapshot("alice", swarm["id"], include_memory=False) == before
    assert (
        await store.call(lambda db: db.execute("SELECT count(*) FROM swarm_groups").fetchone()[0])
        == 1
    )


@pytest.mark.parametrize("invalid", ["home", "other-project", "shared"])
async def test_project_main_rejects_unsafe_existing_team_bindings(project_runtime, invalid):
    runtime, _, state = project_runtime
    home = await runtime.conversations.main("alice")
    leader = (
        home if invalid == "home" else await runtime.conversations.create("alice", "Project leader")
    )
    swarm = await runtime.swarms.create(
        "alice",
        {
            "name": "Existing",
            "goal": "User goal",
            "commandKey": "existing",
            "mainConversationId": leader["id"],
            "target": {
                "kind": "project",
                "projectId": "other" if invalid == "other-project" else "registered",
            },
        },
    )
    if invalid == "shared":
        await runtime.swarms.create(
            "alice",
            {
                "name": "Another team",
                "goal": "Other goal",
                "commandKey": "other-team",
                "mainConversationId": leader["id"],
                "target": {"kind": "project", "projectId": "other"},
            },
        )
    state["workspace"] = {"swarm": swarm["id"]}
    result = await create_goal(runtime)
    assert result.status_code == 409, result.text


async def test_project_swarm_defaults_to_persistent_coordinator_and_cannot_cross_projects(
    project_runtime,
):
    runtime, _, _ = project_runtime
    first = await runtime.swarms.create(
        "alice",
        {
            "name": "Project team",
            "goal": "User goal",
            "commandKey": "first-team",
            "target": {"kind": "project", "projectId": "registered"},
        },
    )
    assert first["mainConversationId"] == (await create_goal(runtime)).json()["data"]["id"]
    assert first["mainConversationId"] != (await runtime.conversations.main("alice"))["id"]
    with pytest.raises(DomainError, match="PROJECT_OKR_TEAM_CONFLICT"):
        await runtime.swarms.create(
            "alice",
            {
                "name": "Wrong team",
                "goal": "Other goal",
                "commandKey": "wrong-team",
                "mainConversationId": first["mainConversationId"],
                "target": {"kind": "project", "projectId": "other"},
            },
        )


async def test_persistent_main_plans_tasks_and_keeps_instructions_in_shared_chat(
    project_runtime, store
):
    runtime, _, state = project_runtime
    cid = (await create_goal(runtime)).json()["data"]["id"]
    origin = await runtime.conversations.accept(
        "alice", cid, "plan-request", "Plan a bounded read-only check"
    )
    binding = {
        "owner": "alice",
        "conversation": cid,
        "role": "main",
        "turnId": origin["turnId"],
        "toolCallId": "create-team",
    }
    created = await runtime.tools.registry["swarm_create"].handler(
        {
            "name": "Goal team",
            "goal": "Read and check this project's evidence",
            "target": {"kind": "project", "projectId": "registered"},
        },
        binding,
    )
    sid = created["id"]
    await runtime.tools.registry["project_okr_update"].handler(
        {
            "operation": "save",
            "payload": {
                "revision": 0,
                "objective": "User confirmed goal",
                "keyResults": [],
                "swarm": sid,
            },
        },
        binding,
    )
    await runtime.tools.registry["swarm_plan"].handler(
        {
            "swarmId": sid,
            "expectedRevision": 1,
            "items": [
                {
                    "member": "reviewer",
                    "executor": "codex",
                    "title": "Read the existing report",
                    "goal": "Read the existing evidence without editing or publishing",
                    "acceptance": "Report actual findings and missing evidence",
                }
            ],
        },
        {**binding, "toolCallId": "plan"},
    )
    await runtime.swarms.advance({"id": "independent-advance", "aggregate_id": sid})
    snapshot = await runtime.swarms.snapshot("alice", sid, include_memory=False)
    assert len(snapshot["work"]) == 1 and snapshot["work"][0]["task_id"]
    task = await store.call(
        lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (snapshot["work"][0]["task_id"],))
    )
    assert task["origin_conversation_id"] == cid and task["state"] == "queued"
    await runtime.swarms.send(
        "alice",
        sid,
        {
            "commandKey": "main-instruction",
            "text": "@leader Summarize the current task before dispatch",
        },
    )
    updated = await runtime.swarms.snapshot("alice", sid, include_memory=False)
    assert updated["posts"][-1]["text"] == "@leader Summarize the current task before dispatch"
    assert state["workspace"]["swarm"] == sid
    assert (await create_goal(runtime, key="reopen-after-plan")).json()["data"]["id"] == cid


async def test_memory_append_has_concrete_contract_and_preserves_project_scope(
    project_runtime, monkeypatch
):
    runtime, _, _ = project_runtime
    cid = (await create_goal(runtime)).json()["data"]["id"]
    calls = []

    async def operation(settings, pid, action, payload):
        calls.append((pid, action, payload))
        return {"projectId": pid}

    monkeypatch.setattr("roami_agent.tools.project_okr.operation", operation)
    tool = runtime.tools.registry["project_okr_memory_append"]
    args = {"content": "Verified dated knowledge", "expectedSha256": "a" * 64}
    tool.validate(args)
    await tool.handler(args, {"owner": "alice", "conversation": cid, "role": "main"})
    assert calls == [("registered", "memory", {"mode": "append", **args})]
    with pytest.raises(ToolArgumentsError):
        tool.validate({**args, "projectId": "foreign"})
    with pytest.raises(ToolArgumentsError):
        tool.validate({**args, "expectedSha256": "missing"})
    for binding in [
        {"owner": "alice", "conversation": cid, "role": "worker"},
        {"owner": "bob", "conversation": cid},
        {"owner": "alice", "conversation": await runtime.conversations.main("alice")},
    ]:
        if isinstance(binding["conversation"], dict):
            binding["conversation"] = binding["conversation"]["id"]
        with pytest.raises(DomainError):
            await tool.handler(args, binding)
    assert len(calls) == 1
