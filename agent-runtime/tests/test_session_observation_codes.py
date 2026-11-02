"""Unknown observations retain safe reasons without terminalizing or relaunching work."""

import json

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.executors.roami_cli import CodingExecutor, observation_code
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row, rows


async def test_unknown_observation_reason_deduplicates_and_recovers(store):
    runtime = Runtime(store, ConversationModel())
    executor = CodingExecutor(store, runtime.settings)
    try:
        c = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", c["id"], "Work", key="observe", executor="codex", record_intent=True
        )
        await store.call(
            lambda db: db.execute("UPDATE tasks SET state='running' WHERE id=?", (task["id"],)),
            write=True,
        )
        run = await store.call(lambda db: row(db, "SELECT * FROM task_attempts"))
        for code in ["SESSION_TOOL_EVENT_MISMATCH"] * 3 + ["SESSION_LIFECYCLE_UNAVAILABLE"] * 2:
            await executor.record(task, run, {"state": "unknown", "observationErrorCode": code})
        current = (await runtime.tasks.get("alice", task["id"]))["task"]
        assert current["state"] == "running"
        assert current["latestAttempt"]["state"] == "unknown"
        assert current["latestAttempt"]["observationErrorCode"] == "SESSION_LIFECYCLE_UNAVAILABLE"
        assert current["latestAttempt"]["outcomeKnown"] is False
        await executor.record(task, run, {"state": "running", "session": "fixture-session"})
        await executor.record(
            task, run, {"state": "unknown", "observationErrorCode": "private URL"}
        )
        events = await store.call(
            lambda db: rows(
                db,
                "SELECT kind,payload_json FROM events WHERE kind LIKE 'task.observation_%' ORDER BY id",
            )
        )
        assert [e["kind"] for e in events] == [
            "task.observation_unknown",
            "task.observation_unknown",
            "task.observation_recovered",
            "task.observation_unknown",
        ]
        assert (
            json.loads(events[-1]["payload_json"])["errorCode"]
            == "CODING_EXECUTOR_OBSERVATION_UNKNOWN"
        )
        assert "errorCode" not in json.loads(events[-2]["payload_json"])
        assert not await store.call(
            lambda db: row(db, "SELECT id FROM jobs WHERE kind='task.verify'")
        )
        assert (
            await store.call(
                lambda db: db.execute("SELECT count(*) FROM task_attempts").fetchone()[0]
            )
            == 1
        )
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "error,code",
    [
        (DomainError("CODING_EXECUTOR_UNAVAILABLE"), "CODING_EXECUTOR_UNAVAILABLE"),
        (TimeoutError("private diagnostics"), "CODING_EXECUTOR_TIMEOUT"),
        (OSError("private path"), "CODING_EXECUTOR_OBSERVATION_FAILED"),
        (DomainError("private URL"), "CODING_EXECUTOR_OBSERVATION_FAILED"),
    ],
)
def test_observation_error_is_safe(error, code):
    assert observation_code(error) == code
