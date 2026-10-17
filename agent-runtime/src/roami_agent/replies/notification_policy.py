"""Notification preferences delay channel delivery without removing conversation messages."""

import json
from datetime import datetime, timedelta

from roami_agent.dispatch.schedule_clock import local_instant, minute, zone
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row

CATEGORIES = {"task_result", "decision", "reminder", "suggestion"}


def notification_category(source, priority="normal", task_state=None, *, proactive=False):
    if source in {"task", "task_result"}:
        return (
            "decision" if task_state == "waiting_user" or priority == "attention" else "task_result"
        )
    if source in {"decision", "reminder", "suggestion"}:
        return source
    return ("decision" if priority == "attention" else "reminder") if proactive else None


class NotificationPolicy:
    def __init__(self, database, *, timezone_name="UTC", clock=now_ms):
        zone(timezone_name)
        self.db, self.timezone, self.clock = database, timezone_name, clock

    def defaults(self):
        return {
            "timezone": self.timezone,
            "enabled": {category: category != "suggestion" for category in sorted(CATEGORIES)},
            "quietHours": None,
            "attentionBypassesQuiet": False,
            "hidePreview": True,
            "maxSuggestionsPerHour": 1,
        }

    def validate(self, settings):
        if not isinstance(settings, dict) or set(settings) != set(self.defaults()):
            raise DomainError("INVALID_NOTIFICATION_PREFERENCES")
        zone(settings["timezone"])
        categories, quiet = settings["enabled"], settings["quietHours"]
        if (
            not isinstance(categories, dict)
            or set(categories) != CATEGORIES
            or any(type(value) is not bool for value in categories.values())
        ):
            raise DomainError("INVALID_NOTIFICATION_PREFERENCES")
        if quiet is not None:
            if not isinstance(quiet, dict) or set(quiet) != {"start", "end"}:
                raise DomainError("INVALID_NOTIFICATION_PREFERENCES")
            if minute(quiet["start"]) == minute(quiet["end"]):
                raise DomainError("INVALID_NOTIFICATION_PREFERENCES")
        if (
            any(
                type(settings[field]) is not bool
                for field in ("attentionBypassesQuiet", "hidePreview")
            )
            or type(settings["maxSuggestionsPerHour"]) is not int
            or not 1 <= settings["maxSuggestionsPerHour"] <= 24
        ):
            raise DomainError("INVALID_NOTIFICATION_PREFERENCES")
        return settings

    def read(self, db, owner):
        item = row(
            db, "SELECT settings_json FROM notification_preferences WHERE owner_id=?", (owner,)
        )
        return json.loads(item["settings_json"]) if item else self.defaults()

    async def get(self, owner):
        return await self.db.call(lambda db: self.read(db, owner))

    async def replace(self, owner, settings):
        settings = self.validate(settings)

        def write(db):
            db.execute(
                "INSERT INTO notification_preferences VALUES(?,?,?) ON CONFLICT(owner_id) DO UPDATE SET settings_json=excluded.settings_json,updated_ms=excluded.updated_ms",
                (owner, encoded(settings), self.clock()),
            )
            db.execute(
                "UPDATE deliveries SET retry_ms=0 WHERE state='pending' AND channel_id IN (SELECT b.id FROM channel_bindings b JOIN conversations c ON c.id=b.conversation_id WHERE c.owner_id=?)",
                (owner,),
            )

        await self.db.call(write, write=True)
        return settings

    @staticmethod
    def quiet_until(settings, at):
        quiet = settings["quietHours"]
        if quiet is None:
            return at
        tz = zone(settings["timezone"])
        local = datetime.fromtimestamp(at / 1000, tz)
        current = local.time().replace(tzinfo=None)
        start, end = minute(quiet["start"]), minute(quiet["end"])
        overnight = start > end
        inside = current >= start or current < end if overnight else start <= current < end
        if not inside:
            return at
        day = local.date() + timedelta(days=int(overnight and current >= start))
        due = local_instant(day, end, settings["timezone"])
        if due <= at:
            second = datetime.combine(day, end).replace(tzinfo=tz, fold=1)
            due = max(due, int(second.timestamp() * 1000))
        return max(at, due)

    def eligibility(self, db, owner, category, event_id, *, priority="normal", at=None):
        if category not in CATEGORIES or priority not in {"normal", "attention"}:
            raise DomainError("INVALID_NOTIFICATION_CATEGORY")
        at = self.clock() if at is None else at
        settings = self.read(db, owner)
        if not settings["enabled"][category]:
            return {
                "state": "disabled",
                "notBeforeMs": None,
                "hidePreview": settings["hidePreview"],
            }
        due = (
            at
            if priority == "attention" and settings["attentionBypassesQuiet"]
            else self.quiet_until(settings, at)
        )
        if category == "suggestion" and not row(
            db,
            "SELECT event_id FROM notification_send_windows WHERE owner_id=? AND event_id=?",
            (owner, event_id),
        ):
            history = db.execute(
                "SELECT started_ms FROM notification_send_windows WHERE owner_id=? AND category='suggestion' AND started_ms>? ORDER BY started_ms DESC LIMIT 24",
                (owner, at - 3_600_000),
            ).fetchall()
            if len(history) >= settings["maxSuggestionsPerHour"]:
                due = max(due, history[settings["maxSuggestionsPerHour"] - 1][0] + 3_600_000)
        return {
            "state": "ready" if due <= at else "deferred",
            "notBeforeMs": due,
            "hidePreview": settings["hidePreview"],
        }

    async def reserve(self, owner, category, event_id, *, priority="normal"):
        def write(db):
            if not row(
                db,
                "SELECT e.id FROM events e JOIN conversations c ON c.id=e.conversation_id WHERE e.id=? AND c.owner_id=? AND c.deleted_ms IS NULL AND e.kind='message.completed'",
                (event_id, owner),
            ):
                raise DomainError("NOTIFICATION_NOT_FOUND", 404)
            at = self.clock()
            result = self.eligibility(db, owner, category, event_id, priority=priority, at=at)
            if result["state"] == "ready":
                db.execute(
                    "INSERT OR IGNORE INTO notification_send_windows VALUES(?,?,?,?)",
                    (owner, event_id, category, at),
                )
            return result

        return await self.db.call(write, write=True)
