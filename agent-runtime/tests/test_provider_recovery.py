"""Managed recovery must use an explicit owned provider reference, never a recent neighbour."""

import asyncio
import json

import pytest

from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.runner import TaskDispatcher
from roami_agent.dispatch.tasks import Tasks
from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


@pytest.fixture
async def continuation(store):
    conversations = Conversations(store)
    tasks = Tasks(store, conversations)
    cid = (await conversations.create("alice"))["id"]
    task = await tasks.create(
        "alice", cid, "Read reference", key="original", executor="codex", record_intent=True
    )
    source = await store.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    result = {
        "state": "succeeded",
        "summary": "Verified reference",
        "outcomeKnown": True,
        "inputStopped": True,
    }

    def finish(db):
        db.execute("UPDATE tasks SET state='succeeded' WHERE id=?", (task["id"],))
        db.execute(
            "UPDATE task_attempts SET state='succeeded',session_id='original-session',agent_conversation_id='original-provider',result_json=?,finished_ms=1 WHERE id=?",
            (json.dumps(result), source["id"]),
        )

    await store.call(finish, write=True)
    await tasks.revisions.request("alice", task["id"], "Continue reference", 1, "round-two")
    await tasks.revisions.advance()
    task = await store.call(lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],)))
    run = await store.call(
        lambda db: row(
            db,
            "SELECT * FROM task_attempts WHERE task_id=? ORDER BY attempt_no DESC LIMIT 1",
            (task["id"],),
        )
    )
    return tasks, task, source, run


async def test_missing_terminal_uses_only_owned_explicit_provider_reference(continuation, store):
    _, task, source, run = continuation
    executor = CodingExecutor(store, Settings())
    calls = []

    async def command(*args, spec=None):
        calls.append(spec)
        if len(calls) == 1:
            raise DomainError("SESSION_TARGET_NOT_FOUND")
        return {"state": "running", "session": "restored-session"}

    executor.command = command
    await executor.launch(task, run, {"key": run["launch_id"], "sessionId": "original-session"})
    assert len(calls) == 2
    assert calls[1]["resumeFrom"] == source["launch_id"]
    assert calls[1]["resumeProviderId"] == "original-provider"
    assert json.loads(task["intent_json"])["continuation"]["providerRunId"] == source["id"]


@pytest.mark.parametrize(
    "mutation",
    [
        "owner",
        "missing-provider",
        "wrong-session",
        "remote",
        "unknown",
        "not-stopped",
        "stale-revision",
        "wrong-source",
    ],
)
async def test_provider_recovery_rejects_cross_identity_or_uncertain_history(
    continuation, store, mutation
):
    _, task, source, run = continuation

    def change(db):
        if mutation == "owner":
            task["owner_id"] = "bob"
        elif mutation == "missing-provider":
            db.execute(
                "UPDATE task_attempts SET agent_conversation_id=NULL WHERE id=?", (source["id"],)
            )
        elif mutation == "wrong-session":
            db.execute("UPDATE task_attempts SET session_id='other' WHERE id=?", (source["id"],))
        elif mutation == "remote":
            db.execute("UPDATE task_attempts SET node_id='other-node' WHERE id=?", (source["id"],))
        elif mutation == "unknown":
            db.execute("UPDATE task_attempts SET state='unknown' WHERE id=?", (source["id"],))
        elif mutation == "not-stopped":
            db.execute(
                "UPDATE task_attempts SET result_json=? WHERE id=?",
                ('{"outcomeKnown":true,"inputStopped":false}', source["id"]),
            )
        elif mutation == "stale-revision":
            db.execute("UPDATE tasks SET revision=revision+1 WHERE id=?", (task["id"],))
        elif mutation == "wrong-source":
            intent = json.loads(task["intent_json"])
            intent["continuation"]["providerRunId"] = "foreign-attempt"
            task["intent_json"] = json.dumps(intent)

    await store.call(change, write=True)
    executor = CodingExecutor(store, Settings())
    assert await executor.recovery_source(task, run, "original-session") is None


async def test_preinput_failure_preserves_original_provider_for_explicit_next_round(
    continuation, store
):
    tasks, task, source, run = continuation
    no_input = {
        "state": "failed",
        "summary": "SESSION_RECOVERY_STOP_UNCONFIRMED",
        "executionStarted": False,
        "outcomeKnown": True,
        "inputStopped": True,
    }

    def fail(db):
        db.execute("UPDATE tasks SET state='failed' WHERE id=?", (task["id"],))
        db.execute(
            "UPDATE task_attempts SET state='failed',session_id='failed-unconfirmed-terminal',result_json=?,finished_ms=2 WHERE id=?",
            (json.dumps(no_input), run["id"]),
        )

    await store.call(fail, write=True)
    await tasks.revisions.request(
        "alice", task["id"], "Try the original context after checking stop", 2, "round-three"
    )
    await tasks.revisions.advance()
    revised = await store.call(lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],)))
    latest = await store.call(
        lambda db: row(
            db,
            "SELECT * FROM task_attempts WHERE task_id=? ORDER BY attempt_no DESC LIMIT 1",
            (task["id"],),
        )
    )
    intent = json.loads(revised["intent_json"])
    assert intent["target"]["sessionId"] == "original-session"
    assert intent["continuation"]["providerRunId"] == source["id"]
    executor = CodingExecutor(store, Settings())
    assert (await executor.recovery_source(revised, latest, "original-session"))["id"] == source[
        "id"
    ]
    await store.call(
        lambda db: db.execute(
            "UPDATE task_attempts SET result_json=? WHERE id=?",
            ('{"executionStarted":false,"outcomeKnown":false,"inputStopped":true}', run["id"]),
        ),
        write=True,
    )
    assert await executor.recovery_source(revised, latest, "original-session") is None


async def test_explicit_closure_cannot_be_bypassed_by_provider_recovery(continuation, store):
    _, task, source, run = continuation
    await store.call(
        lambda db: db.execute(
            "INSERT INTO task_session_closures(task_id,task_revision,run_id,launch_id,session_id,state,updated_ms) VALUES(?,?,?,?,?,'closed',1)",
            (task["id"], 1, source["id"], source["launch_id"], "original-session"),
        ),
        write=True,
    )
    with pytest.raises(DomainError, match="TASK_SESSION_CLOSED"):
        await CodingExecutor(store, Settings()).recovery_source(task, run, "original-session")


@pytest.mark.parametrize("phantom_continuation", [False, True])
@pytest.mark.parametrize("project_target", [False, True])
async def test_never_started_task_retries_initial_target_without_phantom_session(
    store, tmp_path, phantom_continuation, project_target
):
    conversations = Conversations(store)
    tasks = Tasks(store, conversations)
    cid = (await conversations.create("alice"))["id"]
    original = (
        {"kind": "project", "projectId": "project"}
        if project_target
        else {"kind": "new_session", "directory": str(tmp_path)}
    )
    task = await tasks.create(
        "alice",
        cid,
        "Collect evidence",
        key="preflight",
        executor="claude",
        target=original,
        record_intent=True,
    )
    result = {
        "state": "failed",
        "executionStarted": False,
        "summary": "WORKSPACE_PRIOR_RESULT_MISSING",
    }

    def failed(db):
        if project_target:
            db.execute(
                "UPDATE tasks SET target_json=? WHERE id=?",
                (
                    json.dumps({"projectId": "project", "workspaceId": "original-workspace"}),
                    task["id"],
                ),
            )
        intent = json.loads(
            row(db, "SELECT intent_json FROM tasks WHERE id=?", (task["id"],))["intent_json"]
        )
        if phantom_continuation:
            intent["initialIntent"] = dict(intent)
            intent["target"] = {"kind": "session", "sessionId": "never-created"}
        db.execute(
            "UPDATE tasks SET state='failed',intent_json=? WHERE id=?",
            (json.dumps(intent), task["id"]),
        )
        db.execute(
            "UPDATE task_attempts SET state='failed',session_id='never-created',result_json=?,finished_ms=1 WHERE task_id=?",
            (json.dumps(result), task["id"]),
        )

    await store.call(failed, write=True)
    await tasks.revisions.request("alice", task["id"], "Continue collecting", 1, "retry-preflight")
    await tasks.revisions.advance()
    updated = await store.call(lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],)))
    intent = json.loads(updated["intent_json"])
    assert updated["id"] == task["id"] and updated["revision"] == 2
    expected = {**original, "workspaceId": "original-workspace"} if project_target else original
    assert intent["executor"] == "claude" and intent["target"] == expected
    assert "providerRunId" not in intent["continuation"]


@pytest.mark.parametrize(
    "boundary",
    [
        "started",
        "unknown",
        "provider",
        "explicit-session",
        "unspecified",
        "native",
        "cancel-started",
        "cancel-contradiction",
        "cancel-unknown",
        "cancel-session",
    ],
)
async def test_unstarted_target_preserves_uncertain_or_existing_sessions(store, boundary):
    from roami_agent.storage.task_provider import unstarted_target

    conversations = Conversations(store)
    tasks = Tasks(store, conversations)
    cid = (await conversations.create("alice"))["id"]
    task = await tasks.create(
        "alice", cid, "Read evidence", key="boundary", executor="claude", record_intent=True
    )
    result = {"state": "failed", "executionStarted": False}
    if boundary == "started":
        result["executionStarted"] = True
    if boundary == "unspecified":
        result.pop("executionStarted")
    if boundary.startswith("cancel-"):
        result = {"state": "cancelled"}
        if boundary == "cancel-contradiction":
            result["executionStarted"] = True
        if boundary == "cancel-unknown":
            result["executionStarted"] = None
    initial = (
        {"kind": "session", "sessionId": "original"}
        if boundary == "explicit-session"
        else {"kind": "new_session", "directory": "/tmp"}
    )

    def check(db):
        db.execute(
            "UPDATE task_attempts SET state=?,agent_conversation_id=?,result_json=? WHERE task_id=?",
            (
                "unknown" if boundary == "unknown" else "failed",
                "provider" if boundary == "provider" else None,
                json.dumps(result),
                task["id"],
            ),
        )
        if boundary == "native":
            db.execute(
                "UPDATE task_attempts SET executor_kind='native' WHERE task_id=?", (task["id"],)
            )
        if boundary.startswith("cancel-"):
            db.execute(
                "UPDATE task_attempts SET state='cancelled',started_ms=? WHERE task_id=?",
                (1 if boundary == "cancel-started" else None, task["id"]),
            )
            if boundary == "cancel-session":
                db.execute(
                    "UPDATE task_attempts SET session_id='original-session' WHERE task_id=?",
                    (task["id"],),
                )
        return unstarted_target(db, task, 1, {"initialIntent": {"target": initial}})

    assert await store.call(check, write=True) is None


@pytest.mark.parametrize("legacy_receipt", [False, True])
async def test_queued_cancellation_does_not_block_first_real_session(store, legacy_receipt):
    conversations = Conversations(store)
    tasks = Tasks(store, conversations)
    cid = (await conversations.create("alice"))["id"]
    target = {"kind": "project", "projectId": "project"}
    task = await tasks.create(
        "alice",
        cid,
        "Inspect comments",
        key="queued-first",
        executor="codex",
        target=target,
        record_intent=True,
    )

    def preflight_failed(db):
        db.execute("UPDATE tasks SET state='failed' WHERE id=?", (task["id"],))
        db.execute(
            "UPDATE task_attempts SET state='failed',result_json=? WHERE task_id=?",
            (json.dumps({"state": "failed", "executionStarted": False}), task["id"]),
        )

    await store.call(preflight_failed, write=True)
    await tasks.revisions.request("alice", task["id"], "Inspect comments", 1, "queued-second")
    await tasks.revisions.advance()
    await tasks.cancel("alice", task["id"], expected_revision=2)
    dispatcher = TaskDispatcher(store, tasks, None, None, None, asyncio.Event(), {})
    await dispatcher.cancel()
    verification = await store.call(
        lambda db: row(
            db,
            "SELECT * FROM jobs WHERE aggregate_id=? AND kind='task.verify' ORDER BY rowid DESC LIMIT 1",
            (task["id"],),
        )
    )
    await dispatcher.verify(verification)

    def legacy_target(db):
        cancelled = row(
            db, "SELECT * FROM task_attempts WHERE task_id=? AND attempt_no=2", (task["id"],)
        )
        assert cancelled["state"] == "cancelled" and cancelled["started_ms"] is None
        result = json.loads(cancelled["result_json"])
        assert result["executionStarted"] is False
        if legacy_receipt:
            result.pop("executionStarted")
            db.execute(
                "UPDATE task_attempts SET result_json=? WHERE id=?",
                (json.dumps(result), cancelled["id"]),
            )
        current = row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],))
        intent = json.loads(current["intent_json"])
        intent["target"] = {"kind": "session", "sessionId": "never-created"}
        db.execute("UPDATE tasks SET intent_json=? WHERE id=?", (json.dumps(intent), task["id"]))

    await store.call(legacy_target, write=True)
    await tasks.revisions.request("alice", task["id"], "Continue comments", 2, "queued-third")
    await tasks.revisions.advance()
    current = await store.call(lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],)))
    assert current["revision"] == 3
    assert json.loads(current["intent_json"])["target"] == target
