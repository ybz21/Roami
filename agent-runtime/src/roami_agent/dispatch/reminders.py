"""Explicit reminders commit their firing, message and next due time together."""

import json
from datetime import datetime

from roami_agent.dispatch.schedule_clock import latest_daily, minute, next_daily, zone
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.replies.notifications import Notifications
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row, rows
from roami_agent.storage.transcript_repository import owned


class Reminders:
    def __init__(self, database, *, clock=now_ms):
        self.db, self.clock = database, clock

    @staticmethod
    def view(item):
        return {
            "id": item["id"],
            "conversationId": item["conversation_id"],
            "spec": json.loads(item["spec_json"]),
            "enabled": bool(item["enabled"]),
            "nextDueMs": item["next_due_ms"],
            "createdMs": item["created_ms"],
        }

    async def create(
        self,
        owner,
        cid,
        text,
        key,
        *,
        when_ms=None,
        daily_at=None,
        timezone_name="UTC",
        after_seconds=None,
        source_turn_id=None,
    ):
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text) > 10000
            or not isinstance(key, str)
            or not 1 <= len(key) <= 200
            or sum(value is not None for value in (when_ms, daily_at, after_seconds)) != 1
        ):
            raise DomainError("INVALID_REMINDER")
        zone(timezone_name)
        if after_seconds is not None and (
            type(after_seconds) is not int or not 1 <= after_seconds <= 2_678_400
        ):
            raise DomainError("INVALID_REMINDER")
        if when_ms is not None and (
            isinstance(when_ms, bool)
            or not isinstance(when_ms, int)
            or not 0 <= when_ms <= 8_000_000_000_000
        ):
            raise DomainError("INVALID_REMINDER")
        if daily_at is not None:
            minute(daily_at)
        now = self.clock()
        spec = {
            "text": text,
            "whenMs": when_ms,
            "dailyAt": daily_at,
            "timezone": timezone_name,
            "afterSeconds": after_seconds,
        }

        def write(db):
            owned(db, owner, cid)
            if source_turn_id:
                if not row(
                    db,
                    "SELECT id FROM turns WHERE id=? AND conversation_id=? AND state='running'",
                    (source_turn_id, cid),
                ):
                    raise DomainError("REMINDER_TURN_INACTIVE", 409)
                assert_context_admitted(db, {"id": source_turn_id, "owner_id": owner})
            existing = row(
                db,
                "SELECT * FROM reminder_schedules WHERE owner_id=? AND request_key=?",
                (owner, key),
            )
            if existing:
                if existing["conversation_id"] != cid or json.loads(existing["spec_json"]) != spec:
                    raise DomainError("REMINDER_KEY_CONFLICT", 409)
                return self.view(existing)
            if (
                db.execute(
                    "SELECT COUNT(*) FROM reminder_schedules WHERE owner_id=? AND enabled=1",
                    (owner,),
                ).fetchone()[0]
                >= 100
            ):
                raise DomainError("REMINDER_LIMIT", 409)
            rid = identity()
            due = (
                now + after_seconds * 1000
                if after_seconds is not None
                else (when_ms if when_ms is not None else next_daily(now, daily_at, timezone_name))
            )
            db.execute(
                "INSERT INTO reminder_schedules VALUES(?,?,?,?,?,?,1,?,?)",
                (rid, owner, cid, key, encoded(spec), due, now, now),
            )
            return self.view(row(db, "SELECT * FROM reminder_schedules WHERE id=?", (rid,)))

        return await self.db.call(write, write=True)

    async def list(self, owner, conversation_id=None):
        return await self.db.call(
            lambda db: [
                self.view(item)
                for item in rows(
                    db,
                    "SELECT s.* FROM reminder_schedules s JOIN conversations c ON c.id=s.conversation_id WHERE s.owner_id=? AND c.deleted_ms IS NULL AND (? IS NULL OR s.conversation_id=?) ORDER BY s.enabled DESC,s.created_ms DESC LIMIT 200",
                    (owner, conversation_id, conversation_id),
                )
            ]
        )

    async def cancel(self, owner, schedule_id, *, conversation_id=None, source_turn_id=None):
        def write(db):
            item = row(
                db,
                "SELECT * FROM reminder_schedules WHERE id=? AND owner_id=?",
                (schedule_id, owner),
            )
            if not item or (conversation_id and item["conversation_id"] != conversation_id):
                raise DomainError("REMINDER_NOT_FOUND", 404)
            if source_turn_id:
                if not row(
                    db,
                    "SELECT id FROM turns WHERE id=? AND conversation_id=? AND state='running'",
                    (source_turn_id, item["conversation_id"]),
                ):
                    raise DomainError("REMINDER_TURN_INACTIVE", 409)
                assert_context_admitted(db, {"id": source_turn_id, "owner_id": owner})
            db.execute(
                "UPDATE reminder_schedules SET enabled=0,next_due_ms=NULL,updated_ms=? WHERE id=?",
                (self.clock(), schedule_id),
            )
            return {"id": schedule_id, "enabled": False}

        return await self.db.call(write, write=True)

    async def tick(self):
        at = self.clock()

        def write(db):
            due = rows(
                db,
                "SELECT * FROM reminder_schedules WHERE enabled=1 AND next_due_ms<=? ORDER BY next_due_ms,id LIMIT 32",
                (at,),
            )
            for item in due:
                conversation = row(
                    db,
                    "SELECT deleted_ms FROM conversations WHERE id=?",
                    (item["conversation_id"],),
                )
                if conversation["deleted_ms"] is not None:
                    db.execute(
                        "UPDATE reminder_schedules SET enabled=0,next_due_ms=NULL,updated_ms=? WHERE id=?",
                        (at, item["id"]),
                    )
                    continue
                spec, skipped = json.loads(item["spec_json"]), 0
                firing_due = item["next_due_ms"]
                if spec["dailyAt"] is not None:
                    firing_due = latest_daily(at, spec["dailyAt"], spec["timezone"])
                    tz = zone(spec["timezone"])
                    skipped = max(
                        0,
                        (
                            datetime.fromtimestamp(firing_due / 1000, tz).date()
                            - datetime.fromtimestamp(item["next_due_ms"] / 1000, tz).date()
                        ).days,
                    )
                receipt = Notifications.publish_in_transaction(
                    db,
                    item["owner_id"],
                    item["conversation_id"],
                    spec["text"],
                    source="reminder",
                    dedupe_key=f"{item['id']}:{firing_due}",
                )
                db.execute(
                    "INSERT INTO reminder_firings VALUES(?,?,?,?,?)",
                    (item["id"], firing_due, receipt["eventId"], skipped, at),
                )
                db.execute(
                    "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) VALUES(?,'reminder.fire',?,?,?,'done',?)",
                    (
                        identity(),
                        item["id"],
                        f"reminder.fire:{item['id']}:{firing_due}",
                        encoded(
                            {
                                "dueMs": firing_due,
                                "eventId": receipt["eventId"],
                                "skippedCount": skipped,
                            }
                        ),
                        at,
                    ),
                )
                next_due = (
                    next_daily(at, spec["dailyAt"], spec["timezone"])
                    if spec["dailyAt"] is not None
                    else None
                )
                db.execute(
                    "UPDATE reminder_schedules SET next_due_ms=?,enabled=?,updated_ms=? WHERE id=?",
                    (next_due, int(next_due is not None), at, item["id"]),
                )
            return len(due)

        return await self.db.call(write, write=True)
