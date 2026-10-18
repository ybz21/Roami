"Proactive messages and monotonic read cursors share the canonical conversation log."

import hashlib
import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.replies.notification_policy import notification_category
from roami_agent.storage.database import event, row, rows
from roami_agent.storage.transcript_repository import message, owned


class Notifications:
    def __init__(self, database):
        self.db = database

    async def publish(self, owner, cid, text, *, source: str, dedupe_key: str, priority="normal"):
        if (
            not text.strip()
            or len(text) > 30_000
            or not source
            or not dedupe_key
            or priority not in {"normal", "attention"}
        ):
            raise DomainError("INVALID_NOTIFICATION")
        return await self.db.call(
            lambda db: self.publish_in_transaction(
                db, owner, cid, text, source=source, dedupe_key=dedupe_key, priority=priority
            ),
            write=True,
        )

    @staticmethod
    def publish_in_transaction(
        db, owner, cid, text, *, source, dedupe_key, priority="normal", branch_id=None
    ):
        key = (
            "notice:"
            + hashlib.sha256(encoded([owner, cid, source, dedupe_key]).encode()).hexdigest()
        )
        digest = hashlib.sha256(encoded([text, priority]).encode()).hexdigest()
        conversation = owned(db, owner, cid)
        if branch_id and not row(
            db, "SELECT id FROM branches WHERE id=? AND conversation_id=?", (branch_id, cid)
        ):
            raise DomainError("BRANCH_NOT_FOUND", 404)
        old = row(db, "SELECT * FROM events WHERE event_key=?", (key,))
        if old:
            if json.loads(old["payload_json"])["digest"] != digest:
                raise DomainError("NOTIFICATION_KEY_CONFLICT", 409)
            if branch_id and not row(
                db,
                "SELECT id FROM messages WHERE id=? AND branch_id=?",
                (old["message_id"], branch_id),
            ):
                raise DomainError("NOTIFICATION_KEY_CONFLICT", 409)
            return {"eventId": old["id"], "messageId": old["message_id"], "reused": True}
        mid = message(
            db,
            cid,
            branch_id or conversation["active_branch_id"],
            "assistant",
            {"text": text, "source": source, "proactive": True},
        )
        cursor = event(
            db,
            cid,
            "message.completed",
            {
                "messageId": mid,
                "proactive": True,
                "source": source,
                "priority": priority,
                "digest": digest,
            },
            key=key,
            message_id=mid,
        )
        # Delivery outbox is committed with the message; adapters can fail independently.
        for binding in rows(
            db,
            "SELECT id,json_extract(route_json,'$.kind') AS kind FROM channel_bindings WHERE conversation_id=? AND enabled=1",
            (cid,),
        ):
            db.execute(
                "INSERT INTO deliveries(id,event_id,channel_id,state,category) VALUES(?,?,?,'pending',?)",
                (
                    f"{cursor}:{binding['id']}",
                    cursor,
                    binding["id"],
                    (notification_category(source, priority, proactive=True))
                    if binding["kind"] == "app"
                    else None,
                ),
            )
        return {"eventId": cursor, "messageId": mid, "reused": False}

    async def list(self, owner):
        def read(db):
            return rows(
                db,
                "SELECT e.id,e.conversation_id,e.message_id,m.branch_id,e.payload_json,e.created_ms,"
                "c.title,m.content_json FROM events e JOIN conversations c ON c.id=e.conversation_id "
                "JOIN messages m ON m.id=e.message_id LEFT JOIN conversation_reads r "
                "ON r.conversation_id=c.id AND r.owner_id=c.owner_id WHERE c.owner_id=? "
                "AND c.deleted_ms IS NULL AND m.deleted_ms IS NULL AND e.kind='message.completed' "
                "AND NOT EXISTS (SELECT 1 FROM task_attempts a JOIN branches b ON b.id=a.native_branch_id WHERE b.conversation_id=c.id) "
                "AND e.id>COALESCE(r.event_cursor,0) ORDER BY e.id DESC LIMIT 200",
                (owner,),
            )

        return await self.db.call(read)

    async def unread(self, owner):
        def read(db):
            result = row(
                db,
                "SELECT COUNT(*) AS count FROM events e "
                "JOIN conversations c ON c.id=e.conversation_id "
                "JOIN messages m ON m.id=e.message_id LEFT JOIN conversation_reads r "
                "ON r.conversation_id=c.id AND r.owner_id=c.owner_id WHERE c.owner_id=? "
                "AND c.deleted_ms IS NULL AND m.deleted_ms IS NULL AND e.kind='message.completed' "
                "AND NOT EXISTS (SELECT 1 FROM task_attempts a JOIN branches b ON b.id=a.native_branch_id WHERE b.conversation_id=c.id) "
                "AND e.id>COALESCE(r.event_cursor,0)",
                (owner,),
            )
            return result["count"]

        return await self.db.call(read)

    async def mark_read(self, owner, cid, through_event_id):
        def write(db):
            owned(db, owner, cid)
            if through_event_id < 0:
                raise DomainError("INVALID_READ_CURSOR")
            if through_event_id and not row(
                db,
                "SELECT id FROM events WHERE id=? AND conversation_id=?",
                (through_event_id, cid),
            ):
                raise DomainError("READ_CURSOR_NOT_FOUND", 404)
            db.execute(
                "INSERT INTO conversation_reads(owner_id,conversation_id,event_cursor,updated_ms) "
                "VALUES(?,?,?,?) ON CONFLICT(owner_id,conversation_id) DO UPDATE SET "
                "event_cursor=MAX(event_cursor,excluded.event_cursor),updated_ms=excluded.updated_ms",
                (owner, cid, through_event_id, now_ms()),
            )
            return {
                "conversationId": cid,
                "readThrough": row(
                    db,
                    "SELECT event_cursor FROM "
                    "conversation_reads WHERE owner_id=? AND conversation_id=?",
                    (owner, cid),
                )["event_cursor"],
            }

        return await self.db.call(write, write=True)
