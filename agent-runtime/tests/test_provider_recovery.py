"""Managed recovery must use an explicit owned provider reference, never a recent neighbour."""

import json

import pytest

from roami_agent.conversation.transcript import Conversations
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
