"""Delivery policy never consumes unread messages or lets a model bypass user preferences."""

import pytest
from test_reminders import instant

from roami_agent.conversation.transcript import Conversations
from roami_agent.protocol.errors import DomainError
from roami_agent.replies.notification_policy import NotificationPolicy
from roami_agent.replies.notifications import Notifications


async def test_quiet_hours_defer_attention_unless_owner_explicitly_allows_bypass(store):
    at = instant("2026-10-18T15:00:00")
    policy = NotificationPolicy(store, timezone_name="Asia/Shanghai", clock=lambda: at)
    settings = await policy.get("alice")
    settings["quietHours"] = {"start": "22:00", "end": "08:00"}
    await policy.replace("alice", settings)
    conversation = await Conversations(store).create("alice")
    receipt = await Notifications(store).publish(
        "alice",
        conversation["id"],
        "Please review",
        source="task",
        dedupe_key="review",
        priority="attention",
    )
    result = await policy.reserve("alice", "decision", receipt["eventId"], priority="attention")
    assert result == {
        "state": "deferred",
        "notBeforeMs": instant("2026-10-19T00:00:00"),
        "hidePreview": True,
    }
    assert await Notifications(store).unread("alice") == 1
    settings["attentionBypassesQuiet"] = True
    await policy.replace("alice", settings)
    assert (await policy.reserve("alice", "decision", receipt["eventId"], priority="attention"))[
        "state"
    ] == "ready"
    assert (await policy.get("bob"))["quietHours"] is None
    with pytest.raises(DomainError, match="NOTIFICATION_NOT_FOUND"):
        await policy.reserve("bob", "decision", receipt["eventId"])


async def test_suggestions_require_opt_in_and_rate_limit_counts_events_not_retries(store):
    at = instant("2026-10-18T01:00:00")
    policy = NotificationPolicy(store, clock=lambda: at)
    conversation = await Conversations(store).create("alice")
    notices = Notifications(store)
    first = await notices.publish(
        "alice", conversation["id"], "First suggestion", source="suggestion", dedupe_key="first"
    )
    second = await notices.publish(
        "alice", conversation["id"], "Second suggestion", source="suggestion", dedupe_key="second"
    )
    assert (await policy.reserve("alice", "suggestion", first["eventId"]))["state"] == "disabled"
    settings = await policy.get("alice")
    settings["enabled"]["suggestion"] = True
    await policy.replace("alice", settings)
    assert (await policy.reserve("alice", "suggestion", first["eventId"]))["state"] == "ready"
    assert (await policy.reserve("alice", "suggestion", first["eventId"]))["state"] == "ready"
    result = await policy.reserve("alice", "suggestion", second["eventId"])
    assert result["state"] == "deferred" and result["notBeforeMs"] == at + 3_600_000
    at += 3_600_000
    assert (await policy.reserve("alice", "suggestion", second["eventId"]))["state"] == "ready"
    assert await notices.unread("alice") == 2


async def test_policy_rejects_invalid_settings_before_persistence(store):
    policy = NotificationPolicy(store)
    settings = await policy.get("alice")
    settings["enabled"]["suggestion"] = "true"
    with pytest.raises(DomainError, match="INVALID_NOTIFICATION_PREFERENCES"):
        await policy.replace("alice", settings)
    assert not (await policy.get("alice"))["enabled"]["suggestion"]


def test_quiet_end_handles_repeated_dst_hour():
    settings = {"timezone": "America/New_York", "quietHours": {"start": "00:00", "end": "01:30"}}
    assert NotificationPolicy.quiet_until(settings, instant("2026-11-01T06:15:00")) == instant(
        "2026-11-01T06:30:00"
    )
