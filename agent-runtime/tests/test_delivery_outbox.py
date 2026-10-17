"""External channel claims preserve uncertainty, policy and canonical unread state."""

import pytest
from test_reminders import instant

from roami_agent.conversation.transcript import Conversations
from roami_agent.protocol.errors import DomainError
from roami_agent.replies.delivery_outbox import DeliveryOutbox
from roami_agent.replies.notification_policy import NotificationPolicy
from roami_agent.replies.notifications import Notifications
from roami_agent.storage.database import row, rows


async def fixture(store, at=1000):
    conversation = await Conversations(store).create("alice")
    policy = NotificationPolicy(store, clock=lambda: at)
    outbox = DeliveryOutbox(store, policy, clock=lambda: at)
    notifications = Notifications(store)
    return conversation, policy, outbox, notifications


async def test_outbox_is_committed_with_message_and_claim_is_exclusive_owner_scoped(store):
    conversation, _, outbox, notifications = await fixture(store)
    receipt = await notifications.publish(
        "alice", conversation["id"], "Private reminder text", source="reminder", dedupe_key="one"
    )
    assert len(await store.call(lambda db: rows(db, "SELECT id FROM deliveries"))) == 1
    claim = await outbox.claim("alice")
    assert claim["eventId"] == receipt["eventId"] and claim["body"] == "" and claim["hidePreview"]
    assert claim["badge"] == 1 and claim["conversationId"] == conversation["id"]
    assert not await outbox.claim("alice") and not await outbox.claim("bob")
    with pytest.raises(DomainError, match="DELIVERY_NOT_FOUND"):
        await outbox.settle(
            "bob", claim["id"], claim["claimToken"], {"stage": "adapter_accepted", "accepted": 1}
        )
    await outbox.settle(
        "alice", claim["id"], claim["claimToken"], {"stage": "adapter_accepted", "accepted": 1}
    )
    outcome = (await outbox.list("alice"))[0]["outcome"]
    assert outcome["stage"] == "adapter_accepted" and outcome["deviceDelivered"] is False
    assert await notifications.unread("alice") == 1
    assert not await outbox.list("bob")


async def test_expired_sender_is_unknown_and_cannot_be_claimed_again_but_accepts_late_receipt(
    store,
):
    conversation, _, outbox, notifications = await fixture(store)
    await notifications.publish(
        "alice", conversation["id"], "One operation", source="reminder", dedupe_key="one"
    )
    claim = await outbox.claim("alice")
    outbox.clock = lambda: 31_001
    assert not await outbox.claim("alice")
    assert (await outbox.list("alice"))[0]["outcome"]["stage"] == "unknown"
    accepted = {"stage": "adapter_accepted", "accepted": 1}
    assert (await outbox.settle("alice", claim["id"], claim["claimToken"], accepted))[
        "state"
    ] == "delivered"
    assert (await outbox.settle("alice", claim["id"], claim["claimToken"], accepted))[
        "state"
    ] == "delivered"
    with pytest.raises(DomainError, match="DELIVERY_RECEIPT_CONFLICT"):
        await outbox.settle(
            "alice", claim["id"], claim["claimToken"], {"stage": "failed", "failed": 1}
        )


async def test_known_failure_retries_same_message_with_new_claim_and_old_receipts_cannot_win(store):
    conversation, _, outbox, notifications = await fixture(store)
    await notifications.publish(
        "alice", conversation["id"], "Retry transport only", source="reminder", dedupe_key="one"
    )
    claim = await outbox.claim("alice")
    await outbox.settle("alice", claim["id"], claim["claimToken"], {"stage": "failed", "failed": 1})
    assert not await outbox.claim("alice")
    outbox.clock = lambda: 4000
    again = await outbox.claim("alice")
    assert again["eventId"] == claim["eventId"] and again["claimToken"] != claim["claimToken"]
    assert again["messageId"] == claim["messageId"]
    with pytest.raises(DomainError, match="DELIVERY_CLAIM_CHANGED"):
        await outbox.settle(
            "alice", claim["id"], claim["claimToken"], {"stage": "adapter_accepted", "accepted": 1}
        )
    assert (await outbox.list("alice"))[0]["attempts"] == 2
    assert len((await Conversations(store).messages("alice", conversation["id"]))["messages"]) == 1


async def test_quiet_hours_and_disabled_suggestions_hold_delivery_but_not_unread(store):
    at = instant("2026-10-18T23:00:00")
    conversation, policy, outbox, notifications = await fixture(store, at)
    settings = await policy.get("alice")
    settings["quietHours"] = {"start": "22:00", "end": "08:00"}
    await policy.replace("alice", settings)
    reminder = await notifications.publish(
        "alice", conversation["id"], "Normal", source="reminder", dedupe_key="one"
    )
    await notifications.publish(
        "alice", conversation["id"], "Suggestion", source="suggestion", dedupe_key="two"
    )
    assert not await outbox.claim("alice")
    outcomes = {item["eventId"]: item["outcome"]["stage"] for item in await outbox.list("alice")}
    assert outcomes[reminder["eventId"]] == "deferred" and "disabled" in outcomes.values()
    assert await notifications.unread("alice") == 2
    settings["quietHours"] = None
    settings["hidePreview"] = False
    await policy.replace("alice", settings)
    claim = await outbox.claim("alice")
    assert claim["eventId"] == reminder["eventId"] and claim["body"] == "Normal"
    assert not await outbox.claim("alice")


async def test_already_read_messages_are_not_pushed_and_main_answers_do_not_enter_app_outbox(store):
    from test_runtime import ConversationModel, until

    from roami_agent.app import Runtime

    runtime = Runtime(store, ConversationModel())
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", conversation["id"], "direct", "Quick question")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
        )
        assert not await runtime.deliveries.claim("alice")
        notice = await runtime.notifications.publish(
            "alice",
            conversation["id"],
            "Read before external push",
            source="reminder",
            dedupe_key="one",
        )
        await runtime.notifications.mark_read("alice", conversation["id"], notice["eventId"])
        assert not await runtime.deliveries.claim("alice")
        assert (await runtime.deliveries.list("alice"))[0]["outcome"]["stage"] == "suppressed"
    finally:
        await runtime.close()


async def test_main_reminder_defaults_to_owner_timezone_after_settings_change(store):
    from test_runtime import ConversationModel

    from roami_agent.app import Runtime

    runtime = Runtime(store, ConversationModel())
    try:
        conversation = await runtime.conversations.create("alice")
        turn = await runtime.conversations.accept(
            "alice", conversation["id"], "reminder", "Daily at nine"
        )
        await store.call(
            lambda db: db.execute("UPDATE turns SET state='running' WHERE id=?", (turn["turnId"],)),
            write=True,
        )
        preferences = await runtime.notification_policy.get("alice")
        preferences["timezone"] = "Asia/Shanghai"
        await runtime.notification_policy.replace("alice", preferences)
        result = await runtime.tools.registry["reminder_create"].handler(
            {"text": "Daily review", "dailyAt": "09:00"},
            {
                "owner": "alice",
                "conversation": conversation["id"],
                "turnId": turn["turnId"],
                "toolCallId": "daily",
            },
        )
        assert result["spec"]["timezone"] == "Asia/Shanghai"
    finally:
        await runtime.close()


async def test_known_failures_stop_after_retry_budget_without_generating_another_message(store):
    conversation, _, outbox, notifications = await fixture(store)
    await notifications.publish(
        "alice", conversation["id"], "Bounded retry", source="reminder", dedupe_key="one"
    )
    at = 1000
    outbox.clock = lambda: at
    for number in range(1, 7):
        claim = await outbox.claim("alice")
        assert claim
        await outbox.settle(
            "alice", claim["id"], claim["claimToken"], {"stage": "failed", "failed": 1}
        )
        retry = await store.call(
            lambda db, claim=claim: row(
                db, "SELECT retry_ms FROM deliveries WHERE id=?", (claim["id"],)
            )
        )
        if number < 6:
            at = retry["retry_ms"] + 1
        else:
            assert retry["retry_ms"] is None
    at += 10_000_000
    assert not await outbox.claim("alice")
    assert (await outbox.list("alice"))[0]["attempts"] == 6
    assert await notifications.unread("alice") == 1


async def test_forgotten_message_is_not_sent_and_category_preferences_are_independent(store):
    conversation, policy, outbox, notifications = await fixture(store)
    forgotten = await notifications.publish(
        "alice", conversation["id"], "Forgotten", source="reminder", dedupe_key="forget"
    )
    await store.call(
        lambda db: db.execute(
            "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES(?,?,'test',1)",
            ("alice", forgotten["messageId"]),
        ),
        write=True,
    )
    assert not await outbox.claim("alice")
    assert (await outbox.list("alice"))[0]["outcome"]["reason"] == "CONTEXT_SOURCE_FORGOTTEN"
    preferences = await policy.get("alice")
    preferences["enabled"]["task_result"] = False
    await policy.replace("alice", preferences)
    task = await notifications.publish(
        "alice", conversation["id"], "Task result", source="task", dedupe_key="task"
    )
    reminder = await notifications.publish(
        "alice", conversation["id"], "Reminder", source="reminder", dedupe_key="reminder"
    )
    assert (await outbox.claim("alice"))["eventId"] == reminder["eventId"]
    task_outcome = next(
        item for item in await outbox.list("alice") if item["eventId"] == task["eventId"]
    )
    assert task_outcome["outcome"]["stage"] == "disabled"


async def test_schema_upgrade_does_not_push_the_existing_unread_archive(tmp_path, monkeypatch):
    import roami_agent.storage.database as database_module
    from roami_agent.storage import migrations
    from roami_agent.storage.database import Database, event
    from roami_agent.storage.transcript_repository import message

    root = tmp_path / "upgraded"
    database = Database(root / "runtime.db", root, managed=False)
    with monkeypatch.context() as old:
        old.setattr(migrations, "SCHEMA_VERSION", 4)
        old.setattr(database_module, "SCHEMA_VERSION", 4)
        await database.open()
        conversation = await Conversations(database).create("alice")

        def archive(db):
            mid = message(
                db,
                conversation["id"],
                conversation["active_branch_id"],
                "assistant",
                {"text": "Archived unread reminder"},
            )
            return event(
                db,
                conversation["id"],
                "message.completed",
                {"source": "reminder", "proactive": True},
                message_id=mid,
            )

        archived = await database.call(archive, write=True)
        await database.close()
    database = Database(root / "runtime.db", root, managed=False)
    await database.open()
    try:
        policy = NotificationPolicy(database)
        outbox = DeliveryOutbox(database, policy)
        assert not await outbox.claim("alice")
        fresh = await Notifications(database).publish(
            "alice", conversation["id"], "Fresh reminder", source="reminder", dedupe_key="new"
        )
        claim = await outbox.claim("alice")
        assert claim["eventId"] == fresh["eventId"] != archived
        assert claim["badge"] == 2
    finally:
        await database.close()
