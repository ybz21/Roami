"""Late stop evidence releases only a matching workspace and preserves task uncertainty."""

import asyncio
import json

import pytest

from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.resource_leases import ResourceLeases
from roami_agent.dispatch.tasks import Tasks
from roami_agent.executors.native_reconciliation import NativeWorkspaceReconciliation
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import event, row
from roami_agent.storage.transcript_repository import message


async def abandoned(store, *, tool=None, stopped=True):
    conversations = Conversations(store)
    conversation = await conversations.create("alice")
    task = await Tasks(store, conversations).create(
        "alice",
        conversation["id"],
        "native work",
        key=identity(),
        record_intent=True,
        target={"kind": "new_session", "directory": str(store.data_root)},
    )

    def start(db):
        run = row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
        branch = row(db, "SELECT * FROM branches WHERE id=?", (run["native_branch_id"],))
        turn = identity()
        db.execute(
            "INSERT INTO turns(id,conversation_id,branch_id,trigger_kind,state,created_ms) VALUES(?,?,?,'user','running',?)",
            (turn, branch["conversation_id"], branch["id"], now_ms()),
        )
        db.execute("UPDATE tasks SET state='running' WHERE id=?", (task["id"],))
        db.execute("UPDATE task_attempts SET state='running' WHERE id=?", (run["id"],))
        event(
            db,
            conversation["id"],
            "task.preparing",
            {"runId": run["id"], "nativeTurnId": turn},
            task_id=task["id"],
            turn_id=turn,
        )
        mid = message(
            db,
            branch["conversation_id"],
            branch["id"],
            "assistant",
            {"text": "partial"},
            turn_id=turn,
        )
        if tool:
            db.execute(
                "INSERT INTO tool_calls(id,turn_id,assistant_message_id,tool_name,arguments_json,effect,state,idempotency_key,created_ms,updated_ms) VALUES(?,?,?,?,?,'write','unknown',?,?,?)",
                (identity(), turn, mid, tool, "{}", turn + ":call", now_ms(), now_ms()),
            )
        return run, turn

    run, turn = await store.call(start, write=True)
    action = None
    if tool in {"browser_open", "browser_act", "computer_act"}:
        leases = ResourceLeases(store)
        lease = await leases.claim(
            "alice",
            task["id"],
            run["id"],
            "desktop" if tool == "computer_act" else "browser",
            "fixture:" + identity(),
        )
        observation = await leases.observe(
            "alice", lease["id"], task["id"], run["id"], lease["lease_epoch"], "a" * 64, {}
        )
        action = await leases.begin(
            "alice",
            lease["id"],
            task["id"],
            run["id"],
            lease["lease_epoch"],
            observation["id"],
            observation["sceneEpoch"],
            {"kind": "click"},
            turn
            + ":call"
            + {"browser_open": ":create", "browser_act": ":act", "computer_act": ":desktop"}[tool],
        )
        await leases.finish(
            "alice", action["id"], "unknown", {"inputStopped": stopped, "outcomeKnown": False}
        )

    def interrupt(db):
        db.execute("UPDATE tasks SET state='interrupted' WHERE id=?", (task["id"],))
        db.execute("UPDATE task_attempts SET state='unknown' WHERE id=?", (run["id"],))
        db.execute("UPDATE turns SET state='interrupted' WHERE id=?", (turn,))
        db.execute(
            "UPDATE jobs SET state='failed' WHERE aggregate_id=? AND kind='task.run'", (task["id"],)
        )
        return dict(
            row(db, "SELECT * FROM task_attempts WHERE id=?", (run["id"],)), owner_id="alice"
        )

    return conversation, task, await store.call(interrupt, write=True), turn, action


class CLI:
    def __init__(self):
        self.calls = []
        self.change = {}

    async def __call__(self, key, proof):
        self.calls.append((key, proof))
        return {
            "released": True,
            "inputStopped": True,
            "launchKey": key,
            "evidenceSha256": proof["evidenceSha256"],
            "workspaceId": "prepared-workspace",
            **self.change,
        }


@pytest.mark.parametrize("tool", [None, "browser_open", "browser_act", "computer_act"])
async def test_late_stop_releases_once_without_promoting_task_or_replaying_tools(store, tool):
    conversation, task, run, _, action = await abandoned(store, tool=tool)
    cli = CLI()
    service = NativeWorkspaceReconciliation(
        store, Settings(), command=cli, resources=ResourceLeases(store)
    )
    for _ in range(4):
        await service.tick()
    assert len(cli.calls) == 1 and cli.calls[0][0] == run["launch_id"]
    current = await store.call(
        lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],))
    )
    assert current["state"] == "interrupted"
    attempt = await store.call(
        lambda db: row(db, "SELECT state,result_json FROM task_attempts WHERE id=?", (run["id"],))
    )
    assert attempt == {"state": "unknown", "result_json": None}
    if action:
        resource = await store.call(
            lambda db: row(
                db,
                "SELECT state,owner_run_id,lease_until_ms FROM resources WHERE id=?",
                (action["resource_id"],),
            )
        )
        assert resource == {"state": "idle", "owner_run_id": None, "lease_until_ms": None}

    events = await Conversations(store).events("alice", conversation["id"])
    reconciled = [item for item in events if item["kind"] == "task.native_workspace_reconciled"]
    assert len(reconciled) == 1 and reconciled[0]["payload"]["goalStatePreserved"] is True


@pytest.mark.parametrize(
    "tool,stopped",
    [("browser_act", False), ("shell", True), ("http_write", True), ("mcp_write", True)],
)
async def test_unconfirmed_or_unsupported_write_never_releases_workspace(store, tool, stopped):
    await abandoned(store, tool=tool, stopped=stopped)
    cli = CLI()
    await NativeWorkspaceReconciliation(store, Settings(), command=cli).tick()
    assert not cli.calls


@pytest.mark.parametrize(
    "failure",
    [
        "active-run",
        "active-turn",
        "active-job",
        "wrong-turn",
        "missing-prompt-source",
        "running-action",
        "missing-stop",
        "foreign-action",
        "wrong-resource-kind",
    ],
)
async def test_incomplete_or_wrong_scope_evidence_cannot_release(store, failure):
    _, _, run, turn, action = await abandoned(store, tool="browser_act")

    def change(db):
        if failure == "active-run":
            db.execute("UPDATE task_attempts SET state='running' WHERE id=?", (run["id"],))
        elif failure == "active-turn":
            db.execute("UPDATE turns SET state='running' WHERE id=?", (turn,))
        elif failure == "active-job":
            db.execute(
                "UPDATE jobs SET state='running' WHERE aggregate_id=? AND kind='task.run'",
                (run["task_id"],),
            )
        elif failure == "wrong-turn":
            db.execute(
                "UPDATE events SET payload_json=json_set(payload_json,'$.nativeTurnId','wrong') WHERE kind='task.preparing' AND task_id=?",
                (run["task_id"],),
            )
        elif failure == "missing-prompt-source":
            db.execute(
                "DELETE FROM events WHERE kind='task.preparing' AND task_id=?", (run["task_id"],)
            )
        elif failure == "running-action":
            db.execute("UPDATE resource_actions SET state='running' WHERE id=?", (action["id"],))
        elif failure == "missing-stop":
            db.execute("UPDATE resource_actions SET result_json=NULL WHERE id=?", (action["id"],))
        elif failure == "wrong-resource-kind":
            db.execute("UPDATE resources SET kind='desktop' WHERE id=?", (action["resource_id"],))
        elif failure == "foreign-action":
            db.execute(
                "UPDATE resource_actions SET idempotency_key='other:call:act' WHERE id=?",
                (action["id"],),
            )

    await store.call(change, write=True)
    cli = CLI()
    await NativeWorkspaceReconciliation(store, Settings(), command=cli).tick()
    assert not cli.calls


@pytest.mark.parametrize(
    "change",
    [
        {"released": False},
        {"inputStopped": False},
        {"launchKey": "wrong"},
        {"evidenceSha256": "wrong"},
        {"workspaceId": None},
    ],
)
async def test_mismatched_cli_ack_cannot_publish_stop_confirmation(store, change):
    conversation, _, _, _, _ = await abandoned(store)
    cli = CLI()
    cli.change = change
    await NativeWorkspaceReconciliation(store, Settings(), command=cli).tick()
    events = await Conversations(store).events("alice", conversation["id"])
    assert not any(item["kind"] == "task.native_workspace_reconciled" for item in events)


async def test_unmanaged_runtime_cannot_fall_back_to_host_default_instance(store, monkeypatch):
    await abandoned(store)

    async def forbidden(*args, **kwargs):
        raise AssertionError("unbound instance spawned CLI")

    monkeypatch.setattr("roami_agent.executors.native_reconciliation.execute", forbidden)
    await NativeWorkspaceReconciliation(store, Settings()).tick()


async def test_managed_cli_uses_bound_paths_and_excludes_provider_credentials(store, monkeypatch):
    await abandoned(store)
    root = str(store.data_root)
    store.instance_paths = {
        "homeRoot": root,
        "dataRoot": root,
        "databaseRoot": root + "/database",
        "backupRoot": root + "/backups",
    }
    monkeypatch.setenv("ROAMI_HOME", "/unrelated")
    monkeypatch.setenv("ROAMI_AGENT_API_KEY", "fixture")
    calls = []

    async def command(args, *, input_data, timeout, env):
        calls.append(args)
        proof = json.loads(input_data)
        assert env["ROAMI_HOME"] == root and env["ROAMI_DATA"] == root
        assert "ROAMI_AGENT_API_KEY" not in env and timeout == 8
        return {
            "exitCode": 0,
            "stdout": encoded(
                {
                    "released": True,
                    "inputStopped": True,
                    "launchKey": args[args.index("--key") + 1],
                    "evidenceSha256": proof["evidenceSha256"],
                    "workspaceId": "bound-workspace",
                }
            ),
        }

    monkeypatch.setattr("roami_agent.executors.native_reconciliation.execute", command)
    await NativeWorkspaceReconciliation(store, Settings()).tick()
    assert len(calls) == 1


async def test_slow_stop_receipt_does_not_block_main_conversation(store):
    from roami_agent.app import Runtime
    from roami_agent.protocol.models import ModelEvent

    class Model:
        model = "native-reconciliation-latency-fixture"

        async def stream(self, messages, tools):
            yield ModelEvent("text", "responsive")

    conversation, _, _, _, _ = await abandoned(store)
    entered, release = asyncio.Event(), asyncio.Event()
    cli = CLI()

    async def command(key, proof):
        entered.set()
        await release.wait()
        return await cli(key, proof)

    service = NativeWorkspaceReconciliation(store, Settings(), command=command)
    runtime = Runtime(store, Model())
    await runtime.start()
    reconciling = asyncio.create_task(service.tick())
    try:
        await asyncio.wait_for(entered.wait(), 2)
        receipt = await runtime.chat.submit("alice", conversation["id"], "quick", "hello")
        async with asyncio.timeout(1):
            while True:
                turn = await store.call(
                    lambda db: row(db, "SELECT state FROM turns WHERE id=?", (receipt["turnId"],))
                )
                if turn["state"] == "completed":
                    break
                await asyncio.sleep(0.01)
        assert not reconciling.done() and not release.is_set()
    finally:
        release.set()
        await asyncio.gather(reconciling, return_exceptions=True)
        await runtime.close()
