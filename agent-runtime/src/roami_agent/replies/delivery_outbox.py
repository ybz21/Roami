"""Channel claims are durable; an expired sender is uncertain, never safe to replay."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.replies.notification_policy import notification_category
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row, rows


class DeliveryOutbox:
    def __init__(self, database, policy, *, clock=now_ms):
        self.db, self.policy, self.clock = database, policy, clock

    def ingest(self, db, owner, at):
        db.execute("INSERT OR IGNORE INTO notification_delivery_cursors VALUES(?,0)", (owner,))
        cursor = row(
            db, "SELECT event_cursor FROM notification_delivery_cursors WHERE owner_id=?", (owner,)
        )["event_cursor"]
        events = rows(
            db,
            "SELECT e.*,m.content_json,m.branch_id FROM events e JOIN conversations c ON c.id=e.conversation_id "
            "JOIN messages m ON m.id=e.message_id WHERE c.owner_id=? AND c.deleted_ms IS NULL "
            "AND m.deleted_ms IS NULL AND e.kind='message.completed' AND e.id>? "
            "AND NOT EXISTS(SELECT 1 FROM task_attempts a JOIN branches b ON b.id=a.native_branch_id WHERE b.conversation_id=c.id) "
            "ORDER BY e.id LIMIT 128",
            (owner, cursor),
        )
        for item in events:
            payload, content = json.loads(item["payload_json"]), json.loads(item["content_json"])
            source = payload.get("source", content.get("source"))
            category = notification_category(
                source,
                payload.get("priority", "normal"),
                payload.get("taskState"),
                proactive=payload.get("proactive", False),
            )
            if category is None:
                continue
            binding = "agent.app:" + item["conversation_id"]
            db.execute(
                "INSERT OR IGNORE INTO channel_bindings VALUES(?,?,'im',?,1,?)",
                (binding, item["conversation_id"], encoded({"kind": "app"}), at),
            )
            db.execute(
                "INSERT OR IGNORE INTO deliveries(id,event_id,channel_id,state,category,updated_ms) VALUES(?,?,?,'pending',?,?) ON CONFLICT(event_id,channel_id) DO UPDATE SET category=COALESCE(deliveries.category,excluded.category)",
                ("agent.app:" + str(item["id"]), item["id"], binding, category, at),
            )
        last = (
            events[-1]["id"]
            if len(events) == 128
            else db.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
        )
        db.execute(
            "UPDATE notification_delivery_cursors SET event_cursor=? WHERE owner_id=?",
            (last, owner),
        )

    @staticmethod
    def suppress(db, item, at, reason):
        db.execute(
            "UPDATE deliveries SET state='failed',retry_ms=NULL,result_json=?,updated_ms=? WHERE id=?",
            (
                encoded({"stage": "suppressed", "reason": reason, "deviceDelivered": False}),
                at,
                item["id"],
            ),
        )

    async def claim(self, owner):
        at = self.clock()

        def write(db):
            self.ingest(db, owner, at)
            db.execute(
                "UPDATE deliveries SET state='unknown',result_json=?,updated_ms=? WHERE state='sending' AND claim_until_ms<=? AND channel_id IN (SELECT b.id FROM channel_bindings b JOIN conversations c ON c.id=b.conversation_id WHERE c.owner_id=? AND json_extract(b.route_json,'$.kind')='app')",
                (
                    encoded(
                        {
                            "stage": "unknown",
                            "reason": "SENDER_RECEIPT_MISSING",
                            "deviceDelivered": False,
                        }
                    ),
                    at,
                    at,
                    owner,
                ),
            )
            items = rows(
                db,
                "SELECT d.*,e.conversation_id,e.message_id,e.turn_id,e.payload_json,m.content_json,m.branch_id,m.deleted_ms,c.title,c.deleted_ms AS conversation_deleted_ms,r.event_cursor AS read_cursor "
                "FROM deliveries d JOIN channel_bindings b ON b.id=d.channel_id JOIN conversations c ON c.id=b.conversation_id "
                "JOIN events e ON e.id=d.event_id JOIN messages m ON m.id=e.message_id LEFT JOIN conversation_reads r ON r.conversation_id=c.id AND r.owner_id=c.owner_id "
                "WHERE c.owner_id=? AND b.enabled=1 AND json_extract(b.route_json,'$.kind')='app' AND d.state IN ('pending','failed') "
                "AND (d.state='pending' OR d.retry_ms IS NOT NULL) AND COALESCE(d.retry_ms,0)<=? ORDER BY d.event_id LIMIT 32",
                (owner, at),
            )
            for item in items:
                payload = json.loads(item["payload_json"])
                if (
                    item["deleted_ms"] is not None
                    or item["conversation_deleted_ms"] is not None
                    or item["event_id"] <= (item["read_cursor"] or 0)
                ):
                    self.suppress(db, item, at, "ALREADY_READ_OR_REMOVED")
                    continue
                task_id = payload.get("taskId")
                if task_id:
                    task = row(
                        db,
                        "SELECT revision,state FROM tasks WHERE id=? AND owner_id=?",
                        (task_id, owner),
                    )
                    if (
                        not task
                        or task["revision"] != payload.get("taskRevision")
                        or task["state"] != payload.get("taskState")
                        or row(
                            db,
                            "SELECT id FROM jobs WHERE kind='task.steer' AND aggregate_id=? AND state='queued'",
                            (task_id,),
                        )
                    ):
                        self.suppress(db, item, at, "TASK_RESULT_SUPERSEDED")
                        continue
                try:
                    if item["turn_id"]:
                        assert_context_admitted(db, {"owner_id": owner, "id": item["turn_id"]})
                    if row(
                        db,
                        "SELECT message_id FROM context_omissions WHERE owner_id=? AND message_id=?",
                        (owner, item["message_id"]),
                    ):
                        raise DomainError("CONTEXT_SOURCE_FORGOTTEN", 409)
                except DomainError:
                    self.suppress(db, item, at, "CONTEXT_SOURCE_FORGOTTEN")
                    continue
                category = item["category"] or (
                    "reminder" if payload.get("proactive") else "task_result"
                )
                priority = payload.get(
                    "priority", "attention" if category == "decision" else "normal"
                )
                eligibility = self.policy.eligibility(
                    db, owner, category, item["event_id"], priority=priority, at=at
                )
                if eligibility["state"] != "ready":
                    db.execute(
                        "UPDATE deliveries SET retry_ms=?,result_json=?,updated_ms=? WHERE id=?",
                        (
                            eligibility["notBeforeMs"] or at + 60_000,
                            encoded({"stage": eligibility["state"], "deviceDelivered": False}),
                            at,
                            item["id"],
                        ),
                    )
                    continue
                token = identity()
                db.execute(
                    "INSERT OR IGNORE INTO notification_send_windows VALUES(?,?,?,?)",
                    (owner, item["event_id"], category, at),
                )
                db.execute(
                    "UPDATE deliveries SET state='sending',attempts=attempts+1,claim_token=?,claim_until_ms=?,retry_ms=NULL,result_json=?,updated_ms=? WHERE id=?",
                    (
                        token,
                        at + 30_000,
                        encoded({"stage": "sending", "deviceDelivered": False}),
                        at,
                        item["id"],
                    ),
                )
                text = json.loads(item["content_json"]).get("text", "")
                return {
                    "id": item["id"],
                    "claimToken": token,
                    "eventId": item["event_id"],
                    "conversationId": item["conversation_id"],
                    "branchId": item["branch_id"],
                    "messageId": item["message_id"],
                    "hidePreview": eligibility["hidePreview"],
                    "title": "Roami" if eligibility["hidePreview"] else item["title"][:100],
                    "body": "" if eligibility["hidePreview"] else text[:300],
                    "badge": self.unread(db, owner),
                }
            return None

        return await self.db.call(write, write=True)

    @staticmethod
    def unread(db, owner):
        return db.execute(
            "SELECT COUNT(*) FROM events e JOIN conversations c ON c.id=e.conversation_id JOIN messages m ON m.id=e.message_id LEFT JOIN conversation_reads r ON r.conversation_id=c.id AND r.owner_id=c.owner_id WHERE c.owner_id=? AND c.deleted_ms IS NULL AND m.deleted_ms IS NULL AND e.kind='message.completed' AND e.id>COALESCE(r.event_cursor,0) AND NOT EXISTS(SELECT 1 FROM task_attempts a JOIN branches b ON b.id=a.native_branch_id WHERE b.conversation_id=c.id)",
            (owner,),
        ).fetchone()[0]

    async def settle(self, owner, delivery_id, token, outcome):
        if outcome.get("stage") not in {
            "adapter_accepted",
            "failed",
            "unknown",
            "no_devices",
        } or any(
            type(outcome.get(key, 0)) is not int or not 0 <= outcome.get(key, 0) <= 10000
            for key in ("accepted", "failed", "unknown", "noDevices")
        ):
            raise DomainError("INVALID_DELIVERY_RECEIPT")
        if outcome["stage"] == "adapter_accepted" and (
            outcome.get("accepted", 0) < 1 or outcome.get("failed", 0) or outcome.get("unknown", 0)
        ):
            raise DomainError("INVALID_DELIVERY_RECEIPT")
        outcome = {
            key: outcome[key]
            for key in ("stage", "accepted", "failed", "unknown", "noDevices")
            if key in outcome
        }
        outcome["deviceDelivered"] = False
        at = self.clock()

        def write(db):
            item = row(
                db,
                "SELECT d.* FROM deliveries d JOIN channel_bindings b ON b.id=d.channel_id JOIN conversations c ON c.id=b.conversation_id WHERE d.id=? AND c.owner_id=?",
                (delivery_id, owner),
            )
            if not item:
                raise DomainError("DELIVERY_NOT_FOUND", 404)
            if item["claim_token"] != token:
                raise DomainError("DELIVERY_CLAIM_CHANGED", 409)
            if item["state"] not in {"sending", "unknown"}:
                if item["result_json"] == encoded(outcome):
                    return {"id": delivery_id, "state": item["state"]}
                raise DomainError("DELIVERY_RECEIPT_CONFLICT", 409)
            state = {
                "adapter_accepted": "delivered",
                "failed": "failed",
                "unknown": "unknown",
                "no_devices": "failed",
            }[outcome["stage"]]
            retry = (
                at + min(300_000, 1000 * 2 ** min(item["attempts"], 8))
                if state == "failed" and item["attempts"] < 6
                else None
            )
            db.execute(
                "UPDATE deliveries SET state=?,retry_ms=?,result_json=?,updated_ms=? WHERE id=?",
                (state, retry, encoded(outcome), at, delivery_id),
            )
            return {"id": delivery_id, "state": state}

        return await self.db.call(write, write=True)

    async def list(self, owner):
        def read(db):
            return [
                {
                    "id": item["id"],
                    "eventId": item["event_id"],
                    "conversationId": item["conversation_id"],
                    "messageId": item["message_id"],
                    "attempts": item["attempts"],
                    "outcome": json.loads(
                        item["result_json"] or '{"stage":"pending","deviceDelivered":false}'
                    ),
                    "updatedMs": item["updated_ms"],
                }
                for item in rows(
                    db,
                    "SELECT d.*,e.conversation_id,e.message_id FROM deliveries d JOIN events e ON e.id=d.event_id JOIN conversations c ON c.id=e.conversation_id JOIN channel_bindings b ON b.id=d.channel_id WHERE c.owner_id=? AND json_extract(b.route_json,'$.kind')='app' ORDER BY d.event_id DESC LIMIT 50",
                    (owner,),
                )
            ]

        return await self.db.call(read)
