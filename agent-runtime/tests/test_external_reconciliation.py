"""Expired uncertain executions stop consuming slots while their resources remain fenced."""

import json

import pytest

from roami_agent.app import Runtime
from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.tasks import Tasks
from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


class Model:
    model = "injected-reconciliation-model"

    async def stream(self, messages, tools):
        yield ModelEvent(
            "text", "Evidence recorded; work requiring confirmation remains uncertain."
        )


async def prepare_expired(database):
    conversations = Conversations(database)
    tasks = Tasks(database, conversations)
    conversation = await conversations.create("alice")
    task = await tasks.create(
        "alice",
        conversation["id"],
        "External work",
        key="expired",
        executor="codex",
        record_intent=True,
    )

    def update(db):
        budget = json.loads(task["budget_json"])
        budget["deadlineMs"] = now_ms() - 1
        db.execute(
            "UPDATE tasks SET state='running',budget_json=? WHERE id=?",
            (json.dumps(budget), task["id"]),
        )
        db.execute("UPDATE task_attempts SET state='running' WHERE task_id=?", (task["id"],))
        db.execute("UPDATE jobs SET state='done' WHERE aggregate_id=?", (task["id"],))

    await database.call(update, write=True)
    return conversations, tasks, conversation, task


async def test_expired_unknown_execution_frees_slot_and_late_result_stays_historical(store):
    from test_runtime import until

    conversations, tasks, conversation, task = await prepare_expired(store)
    executor = CodingExecutor(store, Settings(workers=1))
    observed = []
    receipt = {"state": "unknown"}

    async def command(sub, *args, **kwargs):
        observed.append(sub)
        return receipt

    executor.command = command
    runtime = Runtime(store, Model(), settings=Settings(workers=1), executor=executor)
    await runtime.start()
    try:
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM tasks WHERE id=? AND state='interrupted'", (task["id"],)
            ),
        )
        attempt = await store.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
        )
        assert attempt["state"] == "unknown"
        assert json.loads(attempt["result_json"])["outcomeKnown"] is False
        assert "launch" not in observed and "cancel" in observed
        other = await tasks.create(
            "alice",
            conversation["id"],
            "Unrelated analysis",
            key="other",
            record_intent=True,
        )
        runtime.wakeup.set()
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM tasks WHERE id=? AND state='succeeded'", (other["id"],)
            ),
        )

        receipt = {
            "state": "succeeded",
            "result": {"state": "succeeded", "summary": "Late evidence"},
        }
        await until(
            store,
            lambda db: row(
                db,
                "SELECT id FROM task_attempts WHERE id=? AND state='succeeded'",
                (attempt["id"],),
            ),
        )
        assert (
            next(item for item in await tasks.list("alice") if item["id"] == task["id"])["state"]
            == "interrupted"
        )
        result = await store.call(
            lambda db: row(db, "SELECT result_json FROM task_attempts WHERE id=?", (attempt["id"],))
        )
        result = json.loads(result["result_json"])
        assert result["summary"] == "Late evidence"
        await tasks.report("alice", task["id"], attempt["id"], 1, result)
        with pytest.raises(DomainError, match="TASK_RESULT_CONFLICT"):
            await tasks.report(
                "alice", task["id"], attempt["id"], 1, dict(result, summary="Conflicting evidence")
            )
        events = await conversations.events("alice", conversation["id"])
        assert sum(item["kind"] == "task.execution_reconciled" for item in events) == 1
        assert (
            sum(
                item["kind"] == "task.interrupted" and item["task_id"] == task["id"]
                for item in events
            )
            == 1
        )
        assert "launch" not in observed
    finally:
        await runtime.close()


async def test_known_result_wins_over_stale_deadline_observation(store):
    _, tasks, _, task = await prepare_expired(store)
    attempt = await store.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    runtime = Runtime(store, Model())
    await tasks.report(
        "alice", task["id"], attempt["id"], 1, {"state": "succeeded", "summary": "Known result"}
    )
    await runtime.dispatch.complete(
        task,
        attempt,
        {"state": "failed", "outcomeKnown": False},
        "interrupted",
        unknown=True,
    )
    current = (await tasks.list("alice"))[0]
    assert current["state"] == "verifying" and current["latestAttempt"]["state"] == "succeeded"
