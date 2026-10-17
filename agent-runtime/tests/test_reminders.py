"""Calendar reminders survive restart and never replay a committed firing."""

from datetime import UTC, datetime

import pytest

from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.reminders import Reminders
from roami_agent.dispatch.schedule_clock import next_daily
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import Database, rows


def instant(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp() * 1000)


async def test_one_shot_is_atomic_idempotent_owned_and_survives_restart(store):
    now = instant("2026-10-18T01:00:00")
    schedules = Reminders(store, clock=lambda: now)
    conversation = await Conversations(store).create("alice")
    first = await schedules.create(
        "alice", conversation["id"], "Review the result", "first", when_ms=now + 1000
    )
    assert (
        await schedules.create(
            "alice", conversation["id"], "Review the result", "first", when_ms=now + 1000
        )
        == first
    )
    with pytest.raises(DomainError, match="REMINDER_KEY_CONFLICT"):
        await schedules.create(
            "alice", conversation["id"], "Changed text", "first", when_ms=now + 1000
        )
    with pytest.raises(DomainError, match="CONVERSATION_NOT_FOUND"):
        await schedules.create("bob", conversation["id"], "Other owner", "other", when_ms=now)
    assert not await schedules.tick()
    await store.close()
    reopened = Database(store.path, store.data_root, managed=False)
    await reopened.open()
    try:
        schedules = Reminders(reopened, clock=lambda: now + 2000)
        assert await schedules.tick() == 1
        assert await schedules.tick() == 0
        assert not (await schedules.list("alice"))[0]["enabled"]
        evidence = await reopened.call(lambda db: rows(db, "SELECT event_id FROM reminder_firings"))
        jobs = await reopened.call(
            lambda db: rows(db, "SELECT payload_json,state FROM jobs WHERE kind='reminder.fire'")
        )
        assert len(evidence) == len(jobs) == 1 and jobs[0]["state"] == "done"
        history = await Conversations(reopened).messages("alice", conversation["id"])
        assert (
            len(history["messages"]) == 1
            and history["messages"][0]["content"]["text"] == "Review the result"
        )
    finally:
        await reopened.close()


async def test_daily_coalesces_missed_dates_and_cancellation_does_not_erase_history(store):
    at = instant("2026-10-18T00:00:00")
    schedules = Reminders(store, clock=lambda: at)
    conversation = await Conversations(store).create("alice")
    reminder = await schedules.create(
        "alice",
        conversation["id"],
        "Daily review",
        "daily",
        daily_at="09:00",
        timezone_name="Asia/Shanghai",
    )
    assert reminder["nextDueMs"] == instant("2026-10-18T01:00:00")
    at = instant("2026-10-21T02:00:00")
    assert await schedules.tick() == 1 and not await schedules.tick()
    firings = await store.call(lambda db: rows(db, "SELECT * FROM reminder_firings"))
    assert firings[0]["due_ms"] == instant("2026-10-21T01:00:00")
    assert firings[0]["skipped_count"] == 3
    with pytest.raises(DomainError, match="REMINDER_NOT_FOUND"):
        await schedules.cancel("bob", reminder["id"])
    await schedules.cancel("alice", reminder["id"])
    at += 86_400_000
    assert not await schedules.tick()
    assert len((await Conversations(store).messages("alice", conversation["id"]))["messages"]) == 1


def test_daily_dst_gap_rolls_forward_and_repeated_hour_only_fires_once():
    assert next_daily(instant("2026-03-08T05:00:00"), "02:30", "America/New_York") == instant(
        "2026-03-08T07:00:00"
    )
    assert next_daily(instant("2026-11-01T04:00:00"), "01:30", "America/New_York") == instant(
        "2026-11-01T05:30:00"
    )
    assert next_daily(instant("2026-11-01T05:40:00"), "01:30", "America/New_York") == instant(
        "2026-11-02T06:30:00"
    )


async def test_message_failure_rolls_back_firing_and_next_due(store, monkeypatch):
    from roami_agent.replies.notifications import Notifications

    schedules = Reminders(store, clock=lambda: 100)
    conversation = await Conversations(store).create("alice")
    reminder = await schedules.create(
        "alice", conversation["id"], "Atomic reminder", "atomic", when_ms=50
    )
    original = Notifications.publish_in_transaction

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected failure after message insertion")

    monkeypatch.setattr(Notifications, "publish_in_transaction", fail)
    with pytest.raises(RuntimeError):
        await schedules.tick()
    assert (await schedules.list("alice"))[0]["nextDueMs"] == reminder["nextDueMs"]
    assert not await store.call(lambda db: rows(db, "SELECT id FROM messages"))
    assert not await store.call(lambda db: rows(db, "SELECT event_id FROM reminder_firings"))
    monkeypatch.setattr(Notifications, "publish_in_transaction", original)
    assert await schedules.tick() == 1


async def test_relative_schedule_retries_do_not_move_due_time_and_inactive_turn_cannot_create(
    store,
):
    at = instant("2026-10-18T01:00:00")
    schedules = Reminders(store, clock=lambda: at)
    conversation = await Conversations(store).create("alice")
    first = await schedules.create(
        "alice", conversation["id"], "Take a break", "relative", after_seconds=60
    )
    at += 30000
    replay = await schedules.create(
        "alice", conversation["id"], "Take a break", "relative", after_seconds=60
    )
    assert replay["nextDueMs"] == first["nextDueMs"] == at + 30000
    with pytest.raises(DomainError, match="REMINDER_TURN_INACTIVE"):
        await schedules.create(
            "alice",
            conversation["id"],
            "Stale model",
            "stale",
            after_seconds=30,
            source_turn_id="absent",
        )


async def test_http_reminders_and_preferences_use_gateway_owner_scope(store):
    import httpx
    from test_runtime import ConversationModel

    from roami_agent.app import Runtime
    from roami_agent.server.http import create_app

    runtime = Runtime(store, ConversationModel())
    try:
        conversation = await runtime.conversations.create("alice")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
            base_url="http://runtime",
            headers={"X-Roami-Owner": "alice"},
        ) as client:
            payload = {
                "conversationId": conversation["id"],
                "requestKey": "http-reminder",
                "text": "HTTP reminder",
                "afterSeconds": 60,
            }
            response = await client.post("/v1/reminders", json=payload)
            assert response.status_code == 200
            rid = response.json()["data"]["id"]
            assert (await client.get("/v1/reminders")).json()["data"][0]["id"] == rid
            assert (await client.get("/v1/reminders", headers={"X-Roami-Owner": "bob"})).json()[
                "data"
            ] == []
            assert (
                await client.delete("/v1/reminders/" + rid, headers={"X-Roami-Owner": "bob"})
            ).status_code == 404
            assert (await client.delete("/v1/reminders/" + rid)).json()["data"]["enabled"] is False
            preferences = (await client.get("/v1/notification-preferences")).json()["data"]
            preferences["hidePreview"] = False
            assert (
                await client.put("/v1/notification-preferences", json={"settings": preferences})
            ).status_code == 200
            assert (
                await client.get("/v1/notification-preferences", headers={"X-Roami-Owner": "bob"})
            ).json()["data"]["hidePreview"] is True
    finally:
        await runtime.close()


async def test_main_creates_reminder_without_dispatching_a_worker(store):
    import json

    from test_runtime import ConversationModel, until

    from roami_agent.app import Runtime
    from roami_agent.protocol.models import ModelEvent
    from roami_agent.storage.database import row

    class ReminderModel(ConversationModel):
        async def stream(self, messages, tools):
            if messages[-1]["role"] == "tool":
                receipt = json.loads(messages[-1]["content"])
                assert receipt["enabled"] and receipt["nextDueMs"] == 61000
                yield ModelEvent("text", "Reminder saved.")
            else:
                yield ModelEvent(
                    "tool",
                    {
                        "id": "save-reminder",
                        "type": "function",
                        "function": {
                            "name": "reminder_create",
                            "arguments": json.dumps({"text": "Review work", "afterSeconds": 60}),
                        },
                    },
                )

    runtime = Runtime(store, ReminderModel(), memory_model=ConversationModel())
    runtime.reminders.clock = lambda: 1000
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit(
            "alice", conversation["id"], "remind-me", "Remind me in one minute to review work"
        )
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
        )
        reminders = await runtime.reminders.list("alice")
        assert len(reminders) == 1 and reminders[0]["spec"]["text"] == "Review work"
        assert not await runtime.tasks.list("alice", conversation["id"])
        assert (await runtime.conversations.messages("alice", conversation["id"]))["messages"][-1][
            "content"
        ]["text"] == "Reminder saved."
    finally:
        await runtime.close()


@pytest.mark.parametrize("daily_at", ["24:00", "09:60", "1 :00", "０９:00", "09-00"])
async def test_invalid_calendar_labels_are_not_saved(store, daily_at):
    conversation = await Conversations(store).create("alice")
    with pytest.raises(DomainError, match="INVALID_SCHEDULE_TIME"):
        await Reminders(store).create(
            "alice", conversation["id"], "Invalid", "bad", daily_at=daily_at
        )
    assert await Reminders(store).list("alice") == []
