import asyncio
import copy
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from test_native_main import fixture_binding, stopped
from test_runtime import until
from test_swarm_provider_generations import prepared

from roami_agent.executors.targets import TargetDirectory
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.migrations import schema_file
from roami_okr.http import create_app
from roami_okr.intake import wake_project
from roami_okr.main import open_main
from roami_okr.main_execution import main_binding

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


async def test_bound_main_reports_pending_native_submission_until_provider_acknowledges(
    wake_runtime, store, monkeypatch
):
    runtime, main, spec, proof, calls = await setup_main(wake_runtime, monkeypatch)
    await runtime.main_executions.configure("alice", main["id"], spec)
    reply = await runtime.chat.submit("alice", main["id"], "typed-once", "Perform existing work")
    team = await runtime.swarms.create(
        "alice",
        {
            "commandKey": "delivery-team",
            "name": "Original team",
            "goal": "Coordinate the existing work",
            "mainConversationId": main["id"],
            "target": {"kind": "project", "projectId": "project"},
        },
        binding={"conversation": main["id"], "turnId": reply["turnId"]},
    )
    acknowledgement = asyncio.Event()
    finish = asyncio.Event()
    pending = {
        "session": proof["sessionId"],
        "sessionBinding": proof["sessionBinding"],
        "state": "unknown",
        "observationErrorCode": "SESSION_SUBMISSION_UNCONFIRMED",
    }
    polls = 0

    async def command(sub, *args, **kwargs):
        nonlocal polls
        calls.append((sub, args, kwargs))
        if sub == "launch":
            return pending
        binding = {**fixture_binding(), "binding": proof["sessionBinding"]}
        if sub == "cancel":
            return stopped(binding, state="cancelled")
        assert sub == "status"
        polls += 1
        if polls == 1:
            await acknowledgement.wait()
            return {**pending, "state": "running", "observationErrorCode": ""}
        await finish.wait()
        return stopped(binding)

    runtime.main_executions.executor.command = command
    await runtime.start()

    def delivery(db, state):
        return row(
            db,
            "SELECT id FROM events WHERE turn_id=? AND kind='turn.native_delivery' "
            "AND json_extract(payload_json,'$.state')=?",
            (reply["turnId"], state),
        )

    await until(store, lambda db: delivery(db, "awaiting_native"))
    snapshot = await runtime.swarms.snapshot("alice", team["id"], include_memory=False)
    assert snapshot["mainState"] == "running"
    assert snapshot["mainSubmission"]["state"] == "awaiting_native"
    assert snapshot["mainModelWait"] is None
    acknowledgement.set()
    await until(store, lambda db: delivery(db, "closed"))
    snapshot = await runtime.swarms.snapshot("alice", team["id"], include_memory=False)
    assert snapshot["mainSubmission"] is None and snapshot["mainState"] == "running"
    finish.set()
    await until(
        store,
        lambda db: row(
            db, "SELECT id FROM turns WHERE id=? AND state='completed'", (reply["turnId"],)
        ),
    )
    assert sum(sub == "launch" for sub, _, _ in calls) == 1


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


@pytest.mark.parametrize("proof_change", [None, "unrelated", "route", "digest", "provider", "time"])
async def test_project_main_recovers_only_its_proven_context_rejection(
    wake_runtime, store, monkeypatch, proof_change
):
    runtime, main, spec, original, _ = await setup_main(wake_runtime, monkeypatch)
    cid = main["id"]
    await runtime.main_executions.configure("alice", cid, spec)
    replacement = prepared("fresh-main", session="fresh-session")
    launches = []
    refusal = {"code": "CLAUDE_COMPACTION_INPUT_REJECTED", "stopEvidenceSha256": "c" * 64}

    async def command(sub, *args, **kwargs):
        if sub == "prepared" and args == ("--key", original["launchKey"]):
            proof = {**copy.deepcopy(original), "contextRejection": refusal}
            if proof_change == "provider":
                proof["sessionBinding"]["providerConversationId"] = "different"
            return proof
        if sub == "prepared" and args == ("--key", replacement["launchKey"]):
            return copy.deepcopy(replacement)
        assert sub == "launch"
        sent = kwargs["spec"]
        launches.append(sent)
        old = sent["sessionId"] == original["sessionId"]
        proof = original if old else replacement
        result = stopped(
            {"session_id": proof["sessionId"], "binding": proof["sessionBinding"]},
            state="failed" if old else "succeeded",
        )
        if old:
            result["result"]["errorCode"] = refusal["code"]
            refusal["launchKey"] = sent["key"]
        return result

    runtime.main_executions.executor.command = command
    await runtime.start()
    first = await runtime.chat.submit("alice", cid, "context-too-large", "Keep coordinating")

    def failed_turn(db):
        return row(
            db, "SELECT finished_ms FROM turns WHERE id=? AND state='failed'", (first["turnId"],)
        )

    await until(store, failed_turn)
    failed = await store.call(failed_turn)
    request = {
        **spec,
        "commandKey": "recover-main",
        "expectedGeneration": 1,
        "preparedLaunchKey": replacement["launchKey"],
        "recoverFromLaunchKey": refusal["launchKey"],
    }
    refusal["finishedMs"] = failed["finished_ms"]
    if proof_change == "time":
        refusal["finishedMs"] += 1
    elif proof_change == "unrelated":
        refusal["launchKey"] = f"project-main:{'a' * 32}:{'b' * 24}"
    elif proof_change == "route":
        refusal["code"] = "CLAUDE_COMPACTION_FAILED"
    elif proof_change == "digest":
        refusal["stopEvidenceSha256"] = "invalid"

    if proof_change is None:
        runtime.settings.updating = True
        following = await runtime.chat.submit(
            "alice", cid, "resume-main", "Continue the original team"
        )
        assert await store.call(
            lambda db: row(db, "SELECT state FROM turns WHERE id=?", (following["turnId"],))
        ) == {"state": "queued"}
    before = (await runtime.conversations.messages("alice", cid))["messages"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        url = f"/v1/conversations/{cid}/execution"
        response = await client.put(url, json=request)
        if proof_change is not None:
            assert response.status_code == 409, response.text
            assert (await client.get(url)).json()["data"]["generation"] == 1
            assert len(launches) == 1
            return
        assert response.status_code == 200, response.text
        assert response.json()["data"] == {
            "conversationId": cid,
            "projectId": "project",
            "generation": 2,
            "executor": "claude",
            "model": "free",
            "sessionId": replacement["sessionId"],
        }
        assert (await client.put(url, json=request)).json() == response.json()
    assert (await runtime.conversations.messages("alice", cid))["messages"] == before
    assert await store.call(
        lambda db: [
            tuple(record)
            for record in db.execute(
                "SELECT generation,session_id FROM project_okr_main_providers "
                "WHERE conversation_id=? ORDER BY generation",
                (cid,),
            )
        ]
    ) == [(1, original["sessionId"]), (2, replacement["sessionId"])]
    assert len(launches) == 1
    runtime.settings.updating = False
    runtime.wakeup.set()
    await until(
        store,
        lambda db: row(
            db, "SELECT id FROM turns WHERE id=? AND state='completed'", (following["turnId"],)
        ),
    )
    assert [sent["sessionId"] for sent in launches] == [
        original["sessionId"],
        replacement["sessionId"],
    ]


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


@pytest.mark.parametrize("change", [None, "profile", "source", "unknown", "wrong-turn"])
async def test_main_adopts_same_provider_after_proven_recovery(
    wake_runtime, store, monkeypatch, change
):
    runtime, main, spec, original, _ = await setup_main(wake_runtime, monkeypatch)
    cid = main["id"]
    original["sessionBinding"].update(
        providerHome="/profile", providerHomeProof="profile-proof", providerHomeExplicit=False
    )
    await runtime.main_executions.configure("alice", cid, spec)
    source = await runtime.chat.submit("alice", cid, "failed-input", "Continue yesterday's review")
    turn_id = source["turnId"]
    await store.call(
        lambda db: (
            db.execute("UPDATE turns SET state='failed' WHERE id=?", (turn_id,)),
            db.execute("UPDATE jobs SET state='failed' WHERE aggregate_id=?", (turn_id,)),
        ),
        write=True,
    )
    group = await runtime.swarms.create(
        "alice",
        {
            "commandKey": "original-team",
            "name": "Original team",
            "goal": "Coordinate original members",
            "mainConversationId": cid,
            "target": {"kind": "project", "projectId": "project"},
        },
    )
    recovery_source = f"project-main:{'f' * 32 if change == 'wrong-turn' else turn_id}:{'b' * 24}"
    recovered = prepared("recovered-main", session="recovered-session", model="gateway-vision")
    recovered["recoveredFrom"] = "unrelated-turn" if change == "source" else recovery_source
    recovered["sessionBinding"].update(
        providerConversationId=original["sessionBinding"]["providerConversationId"],
        providerHome="/other-profile" if change == "profile" else "/profile",
        providerHomeProof="profile-proof",
        providerHomeExplicit=False,
    )
    launches = []

    async def command(sub, *args, **kwargs):
        if sub == "prepared":
            assert args == ("--key", recovered["launchKey"])
            return copy.deepcopy(recovered)
        if sub == "status":
            assert args == ("--key", recovery_source)
            return {
                "state": "failed",
                **stopped(
                    {"session_id": original["sessionId"], "binding": original["sessionBinding"]},
                    state="failed",
                    known=change != "unknown",
                ),
            }
        assert sub == "launch"
        launches.append(kwargs["spec"])
        return stopped(
            {"session_id": recovered["sessionId"], "binding": recovered["sessionBinding"]}
        )

    runtime.main_executions.executor.command = command
    request = {
        **spec,
        "commandKey": "adopt-recovered-main",
        "expectedGeneration": 1,
        "model": recovered["configuredModel"],
        "preparedLaunchKey": recovered["launchKey"],
        "recoverProviderFromLaunchKey": recovery_source,
    }
    before = (await runtime.conversations.messages("alice", cid))["messages"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        url = f"/v1/conversations/{cid}/execution"
        response = await client.put(url, json=request)
        if change is not None:
            assert response.status_code == 409, response.text
            assert (await client.get(url)).json()["data"]["generation"] == 1
            assert not launches
            return
        assert response.status_code == 200, response.text
        assert response.json()["data"] == {
            "conversationId": cid,
            "projectId": "project",
            "generation": 2,
            "executor": "claude",
            "model": recovered["configuredModel"],
            "sessionId": recovered["sessionId"],
        }
        assert (await client.put(url, json=request)).json() == response.json()
    assert (await runtime.conversations.messages("alice", cid))["messages"] == before
    assert not (await runtime.swarms.snapshot("alice", group["id"], include_memory=False))["paused"]
    assert await store.call(
        lambda db: [
            tuple(item)
            for item in db.execute(
                "SELECT generation,session_id,provider_id FROM project_okr_main_providers "
                "WHERE conversation_id=? ORDER BY generation",
                (cid,),
            )
        ]
    ) == [
        (1, original["sessionId"], original["sessionBinding"]["providerConversationId"]),
        (2, recovered["sessionId"], original["sessionBinding"]["providerConversationId"]),
    ]
    await runtime.start()
    follow = await runtime.swarms.send(
        "alice", group["id"], {"commandKey": "follow-recovery", "text": "@main Confirm the history"}
    )
    await until(
        store,
        lambda db: row(
            db, "SELECT id FROM turns WHERE id=? AND state='completed'", (follow["turnId"],)
        ),
    )
    sent = next(item for item in launches if follow["turnId"] in item["key"])
    assert (
        sent["sessionId"] == recovered["sessionId"]
        and sent["preparedFrom"] == recovered["launchKey"]
    )


def test_provider_recovery_schema_preserves_existing_bindings_and_exclusive_ownership():
    with sqlite3.connect(":memory:") as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript(
            "CREATE TABLE project_okr_mains (owner_id TEXT,project_id TEXT,conversation_id TEXT);"
            "INSERT INTO project_okr_mains VALUES ('alice','project','main'),('bob','other','another');"
            + schema_file("0032_project_main_providers.sql")
        )
        insert = "INSERT INTO project_okr_main_providers VALUES (?,?,?,?,?,?,?,?,?,?,?)"
        original = (
            "alice",
            "project",
            "main",
            1,
            "claude",
            "free",
            "old",
            "old",
            "provider",
            "{}",
            1,
        )
        db.execute(insert, original)
        db.executescript(schema_file("0034_project_main_provider_recovery.sql"))
        assert db.execute("SELECT * FROM project_okr_main_providers").fetchone() == original
        db.execute(insert, (*original[:3], 2, "claude", "vision", "new", "new", *original[8:]))
        with pytest.raises(
            sqlite3.IntegrityError, match="PROJECT_MAIN_PROVIDER_OWNERSHIP_CONFLICT"
        ):
            db.execute(
                insert,
                (
                    "bob",
                    "other",
                    "another",
                    1,
                    "claude",
                    "vision",
                    "foreign",
                    "foreign",
                    *original[8:],
                ),
            )
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


async def test_native_provider_cannot_be_reused_by_another_project(wake_runtime, monkeypatch):
    runtime, main, spec, _, _ = await setup_main(wake_runtime, monkeypatch)
    await runtime.main_executions.configure("alice", main["id"], spec)
    other = await open_main(runtime.conversations, "alice", "other-project")

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
        await wake_project(
            runtime.chat, "alice", main["id"], "project", "wake", "Continue the team"
        )
        if scheduled
        else await runtime.chat.submit("alice", main["id"], "direct", "Continue the team")
    )
    assert result["kind"] == "message"
