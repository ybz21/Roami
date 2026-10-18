"""Source forgetting cancels dependent task trees without inventing stop evidence."""

import json

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row, rows


class RecordedExecutor(CodingExecutor):
    def __init__(self, database):
        super().__init__(database, Settings(coding_directory=database.data_root))
        self.calls = []
        self.cancelled = False
        self.confirm_stop = True

    async def command(self, sub, *args, spec=None):
        self.calls.append(sub)
        if sub == "cancel":
            self.cancelled = True
        if self.cancelled and self.confirm_stop:
            return {
                "state": "cancelled",
                "session": "fixture-session",
                "result": {"state": "cancelled", "outcomeKnown": True, "inputStopped": True},
            }
        return {"state": "running", "session": "fixture-session"}


async def task_and_memory(runtime, executor="codex", *, key="private"):
    conversation = await runtime.conversations.create("alice")
    task = await runtime.tasks.create(
        "alice",
        conversation["id"],
        "Private research",
        key=key,
        executor=executor,
        record_intent=True,
    )
    memory = await runtime.memory.save(
        "alice", "Private", "Private research", task["origin_message_id"]
    )
    return conversation, task, memory


@pytest.mark.parametrize("kind", ["codex", "claude"])
@pytest.mark.parametrize("confirm_stop", [False, True])
async def test_forgetting_running_external_task_sends_cancel_and_waits_for_actual_stop(
    store, kind, confirm_stop
):
    executor = RecordedExecutor(store)
    executor.confirm_stop = confirm_stop
    runtime = Runtime(store, ConversationModel(), executor=executor)
    try:
        conversation, task, memory = await task_and_memory(runtime, kind)
        independent = await runtime.tasks.create(
            "alice", conversation["id"], "Public research", key="public", record_intent=True
        )
        job = await store.call(
            lambda db: row(
                db, "SELECT * FROM jobs WHERE kind='task.run' AND aggregate_id=?", (task["id"],)
            )
        )
        await runtime.scheduler._job(job)
        assert executor.calls == ["launch"]
        await runtime.memory.forget("alice", memory["id"])
        current = await store.call(
            lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],))
        )
        assert current["state"] == "cancelling"
        await executor.poll(runtime.tasks)
        assert executor.calls == ["launch", "cancel", "status"]
        if confirm_stop:
            verify = await store.call(
                lambda db: row(
                    db,
                    "SELECT * FROM jobs WHERE kind='task.verify' AND aggregate_id=?",
                    (task["id"],),
                )
            )
            await runtime.dispatch.verify(verify)
        states = {item["id"]: item["state"] for item in await runtime.tasks.list("alice")}
        assert states[task["id"]] == ("cancelled" if confirm_stop else "cancelling")
        assert states[independent["id"]] == "queued"
        assert executor.calls.count("launch") == 1
        projected = await runtime.tasks.list("alice", conversation["id"], for_model=True)
        assert next(item for item in projected if item["id"] == task["id"])["contextExcluded"]
    finally:
        await runtime.close()


async def test_forgetting_cancels_descendants_once_and_preserves_other_owner(store):
    runtime = Runtime(store, ConversationModel())
    try:
        conversation, parent, memory = await task_and_memory(runtime, "native")
        await store.call(
            lambda db: db.execute("UPDATE tasks SET state='running' WHERE id=?", (parent["id"],)),
            write=True,
        )
        child = await runtime.tasks.create(
            "alice", conversation["id"], "Child", key="child", parent_task_id=parent["id"]
        )
        other = await runtime.conversations.create("bob")
        bob_task = await runtime.tasks.create(
            "bob", other["id"], "Private research", key="private", record_intent=True
        )
        await runtime.memory.forget("alice", memory["id"])
        await runtime.memory.forget("alice", memory["id"])
        states = {task["id"]: task["state"] for task in await runtime.tasks.list("alice")}
        assert states == {parent["id"]: "cancelling", child["id"]: "cancelling"}
        events = await store.call(
            lambda db: rows(db, "SELECT * FROM events WHERE kind='task.cancelling'")
        )
        assert len(events) == 2
        assert (await runtime.tasks.list("bob"))[0]["id"] == bob_task["id"]
        assert (await runtime.tasks.list("bob"))[0]["state"] == "queued"
    finally:
        await runtime.close()


async def test_forgetting_and_cancellation_roll_back_together(store):
    runtime = Runtime(store, ConversationModel())
    try:
        _, _, memory = await task_and_memory(runtime)

        def fail_after_cancelling(db, owner):
            runtime.tasks.cancel_forgotten_in_transaction(db, owner)
            raise OSError("fixture transaction failure")

        runtime.memory.cancel_forgotten = fail_after_cancelling
        with pytest.raises(OSError):
            await runtime.memory.forget("alice", memory["id"])
        assert (await runtime.memory.get("alice", memory["id"]))["state"] == "active"
        assert (await runtime.tasks.list("alice"))[0]["state"] == "queued"
        assert (
            await store.call(
                lambda db: db.execute("SELECT COUNT(*) FROM context_omissions").fetchone()[0]
            )
            == 0
        )
        assert (
            await store.call(
                lambda db: db.execute("SELECT COUNT(*) FROM memory_tombstones").fetchone()[0]
            )
            == 0
        )
    finally:
        await runtime.close()


async def test_deleting_memory_without_forgetting_source_keeps_task(store):
    runtime = Runtime(store, ConversationModel())
    try:
        _, task, memory = await task_and_memory(runtime)
        await runtime.memory.forget("alice", memory["id"], forget_sources=False)
        saved = (await runtime.tasks.list("alice"))[0]
        assert saved["id"] == task["id"] and saved["state"] == "queued"
        assert json.loads(saved["intent_json"])["goal"] == "Private research"
    finally:
        await runtime.close()
