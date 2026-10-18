"""Stop receipts fence queued writes before coroutine cancellation is delivered."""

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.database import row


async def active_source(runtime, store):
    conversation = await runtime.conversations.create("alice")
    receipt = await runtime.conversations.accept("alice", conversation["id"], "one", "Research")
    job = await store.call(
        lambda db: row(db, "SELECT * FROM jobs WHERE aggregate_id=?", (receipt["turnId"],))
    )
    turn = await runtime.mailbox.claim(job)
    mid = await runtime.journal.start(turn)
    return conversation, turn, mid


@pytest.mark.parametrize("state", ["queued", "completed", "failed", "interrupted"])
async def test_inactive_model_turn_cannot_delegate(store, state):
    runtime = Runtime(store, ConversationModel())
    try:
        conversation, turn, mid = await active_source(runtime, store)
        await store.call(
            lambda db: db.execute("UPDATE turns SET state=? WHERE id=?", (state, turn["id"])),
            write=True,
        )
        with pytest.raises(DomainError, match="TASK_TURN_INACTIVE"):
            await runtime.tasks.create(
                "alice",
                conversation["id"],
                "Late delegation",
                key="late",
                source_turn_id=turn["id"],
                source_assistant_message_id=mid,
            )
        assert await runtime.tasks.list("alice") == []
    finally:
        await runtime.close()


async def test_stop_receipt_fences_delegation_reminders_and_output_before_cancellation(store):
    runtime = Runtime(store, ConversationModel())
    try:
        conversation, turn, mid = await active_source(runtime, store)
        existing = await runtime.tasks.create(
            "alice",
            conversation["id"],
            "Already delegated",
            key="before-stop",
            source_turn_id=turn["id"],
            source_assistant_message_id=mid,
        )
        await runtime.journal.delta(turn, mid, "Partial", "Partial")
        receipt = await runtime.chat.interrupt("alice", conversation["id"], "stop")
        assert receipt["turnId"] == turn["id"]
        # No loop handle exists: the database turn is still running during this race.
        assert (
            await store.call(lambda db: row(db, "SELECT * FROM turns WHERE id=?", (turn["id"],)))
        )["state"] == "running"
        with pytest.raises(DomainError, match="TURN_INTERRUPTED"):
            await runtime.tasks.create(
                "alice",
                conversation["id"],
                "Late delegation",
                key="after-stop",
                source_turn_id=turn["id"],
                source_assistant_message_id=mid,
            )
        with pytest.raises(DomainError, match="TURN_INTERRUPTED"):
            await runtime.reminders.create(
                "alice",
                conversation["id"],
                "Late reminder",
                key="late-reminder",
                after_seconds=60,
                source_turn_id=turn["id"],
            )
        with pytest.raises(DomainError, match="TURN_INTERRUPTED"):
            await runtime.journal.delta(turn, mid, "Partial late output", " late output")
        with pytest.raises(DomainError, match="TURN_INTERRUPTED"):
            await runtime.briefs.create(
                "alice",
                conversation["id"],
                "Late daily brief",
                "late-brief",
                daily_at="08:00",
                source_turn_id=turn["id"],
            )
        assert await runtime.briefs.list("alice") == []
        with pytest.raises(DomainError, match="TURN_INTERRUPTED"):
            await runtime.journal.finish(
                turn, mid, "Late answer", [], None, 1, final=True, completion=None
            )
        messages = (await runtime.conversations.messages("alice", conversation["id"]))["messages"]
        assert messages[-1]["content"]["text"] == "Partial"
        assert [(task["id"], task["state"]) for task in await runtime.tasks.list("alice")] == [
            (existing["id"], "queued")
        ]
        direct = await runtime.tasks.create(
            "alice", conversation["id"], "Explicit user task", key="direct", record_intent=True
        )
        assert direct["state"] == "queued"
    finally:
        await runtime.close()


async def test_durable_stop_marks_late_model_output_interrupted_even_without_cancel_handle(store):
    class LateModel:
        model = "late-model"

        async def stream(self, messages, tools):
            yield ModelEvent("text", "p" * 1024)
            runtime.turn_tasks.pop(turn["id"])
            await runtime.chat.interrupt("alice", conversation["id"], "stop")
            yield ModelEvent("text", "late")

    runtime = Runtime(store, LateModel())
    try:
        conversation, turn, _ = await active_source(runtime, store)
        with pytest.raises(DomainError, match="TURN_INTERRUPTED"):
            await runtime.loop.run(turn, "main")
        saved = await store.call(
            lambda db: row(db, "SELECT * FROM turns WHERE id=?", (turn["id"],))
        )
        assert saved["state"] == "interrupted"
        view = await runtime.conversations.messages("alice", conversation["id"])
        assert view["messages"][-1]["content"]["text"] == "p" * 1024
        assert view["messages"][-1]["status"] == "interrupted"
        assert not any(
            event["kind"] == "message.completed"
            for event in await runtime.conversations.events("alice", conversation["id"])
        )
    finally:
        await runtime.close()
