"Append-only conversation branches, idempotent intake, and committed event replay."

import hashlib
import json

from roami_agent.conversation.activity import conversation_activity
from roami_agent.conversation.attachments import Attachments
from roami_agent.memory.intake import remember_request
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import Database, event, row, rows
from roami_agent.storage.task_request import task_user_request
from roami_agent.storage.transcript_repository import history, message, owned


class Conversations:
    def __init__(self, database: Database):
        self.db = database

    @staticmethod
    def _new(db, owner, title):
        cid, bid = identity(), identity()
        db.execute("INSERT OR IGNORE INTO owner_versions(owner_id) VALUES(?)", (owner,))
        db.execute(
            "INSERT INTO conversations(id,owner_id,title,created_ms,updated_ms) VALUES(?,?,?,?,?)",
            (cid, owner, title[:200], now_ms(), now_ms()),
        )
        db.execute(
            "INSERT INTO branches(id,conversation_id,created_ms) VALUES(?,?,?)",
            (bid, cid, now_ms()),
        )
        db.execute("UPDATE conversations SET active_branch_id=? WHERE id=?", (bid, cid))
        db.execute(
            "INSERT INTO channel_bindings(id,conversation_id,channel_kind,route_json,created_ms) VALUES(?,?,'im',?,?)",
            ("agent.app:" + cid, cid, encoded({"kind": "app"}), now_ms()),
        )
        event(db, cid, "conversation.created", {"conversationId": cid, "branchId": bid})
        return owned(db, owner, cid)

    async def main(self, owner):
        def write(db):
            existing = row(
                db,
                "SELECT c.* FROM main_conversations m JOIN conversations c ON c.id=m.conversation_id WHERE m.owner_id=? AND c.deleted_ms IS NULL",
                (owner,),
            )
            if existing:
                return existing
            legacy = row(
                db,
                "SELECT c.* FROM conversations c WHERE c.owner_id=? AND c.deleted_ms IS NULL AND NOT EXISTS (SELECT 1 FROM task_attempts a JOIN branches b ON b.id=a.native_branch_id WHERE b.conversation_id=c.id) ORDER BY c.created_ms,c.id LIMIT 1",
                (owner,),
            )
            conversation = legacy or self._new(db, owner, "New conversation")
            db.execute(
                "INSERT INTO main_conversations(owner_id,conversation_id,created_ms) VALUES(?,?,?) ON CONFLICT(owner_id) DO UPDATE SET conversation_id=excluded.conversation_id,created_ms=excluded.created_ms",
                (owner, conversation["id"], now_ms()),
            )
            return conversation

        return await self.db.call(write, write=True)

    async def create(self, owner: str, title="New conversation", *, request_key=None):
        if request_key is not None and (not request_key or len(request_key) > 200):
            raise DomainError("INVALID_REQUEST_KEY")
        digest = hashlib.sha256(encoded(["create_conversation", title]).encode()).hexdigest()

        def write(db):
            if request_key:
                prior = row(
                    db,
                    "SELECT * FROM requests WHERE owner_id=? AND request_key=?",
                    (owner, request_key),
                )
                if prior:
                    if prior["payload_sha256"] != digest:
                        raise DomainError("REQUEST_KEY_CONFLICT", 409)
                    return owned(db, owner, prior["conversation_id"])
            conversation = self._new(db, owner, title)
            cid = conversation["id"]
            if request_key:
                db.execute(
                    "INSERT INTO requests(id,owner_id,request_key,payload_sha256,conversation_id,accepted_ms) VALUES(?,?,?,?,?,?)",
                    (identity(), owner, request_key, digest, cid, now_ms()),
                )
            return owned(db, owner, cid)

        return await self.db.call(write, write=True)

    async def list(self, owner):
        return await self.db.call(
            lambda db: rows(
                db,
                "SELECT c.* FROM conversations c WHERE c.owner_id=? AND c.deleted_ms IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM task_attempts a JOIN branches b ON b.id=a.native_branch_id WHERE b.conversation_id=c.id) "
                "ORDER BY c.updated_ms DESC LIMIT 200",
                (owner,),
            )
        )

    async def get(self, owner, cid):
        return await self.db.call(lambda db: owned(db, owner, cid))

    async def activity_detail(self, owner, cid, aid, branch_id=None):
        from roami_agent.conversation.activity_payloads import activity_payload

        return await self.db.call(lambda db: activity_payload(db, owner, cid, aid, branch_id))

    async def messages(self, owner, cid, branch_id=None):
        def read(db):
            c = owned(db, owner, cid)
            selected = branch_id or c["active_branch_id"]
            if not row(
                db, "SELECT id FROM branches WHERE id=? AND conversation_id=?", (selected, cid)
            ):
                raise DomainError("BRANCH_NOT_FOUND", 404)
            result = history(db, selected)
            message_ids = {entry["id"] for entry in result}
            aliases = {}
            visible = []
            for entry in result:
                content = json.loads(entry["content_json"])
                if content.get("taskSteer"):
                    source = task_user_request(db, entry)
                    if source and source["id"] != entry["id"] and source["id"] in message_ids:
                        aliases[entry["id"]] = source["id"]
                        continue
                visible.append(entry)
            activities = conversation_activity(db, cid, result, main_only=True)
            for activity in activities:
                activity["anchorMessageId"] = aliases.get(
                    activity["anchorMessageId"], activity["anchorMessageId"]
                )
            completed = {
                r["message_id"]: r["id"]
                for r in rows(
                    db,
                    "SELECT id,message_id FROM events WHERE conversation_id=? AND kind='message.completed'",
                    (cid,),
                )
            }
            cursor = db.execute(
                "SELECT COALESCE(MAX(id),0) FROM events WHERE conversation_id=?", (cid,)
            ).fetchone()[0]
            compact = row(
                db,
                "SELECT id,payload_json FROM jobs WHERE kind='context.compact' AND json_extract(payload_json,'$.branchId')=? ORDER BY rowid DESC LIMIT 1",
                (selected,),
            )
            return {
                "compaction": (
                    {"operationId": compact["id"], **json.loads(compact["payload_json"])}
                    if compact
                    else None
                ),
                "conversation": c,
                "branchId": selected,
                "messages": [
                    dict(
                        m,
                        content=json.loads(m["content_json"]),
                        completedEventId=completed.get(m["id"]),
                    )
                    for m in visible
                ],
                "turns": rows(
                    db,
                    "SELECT id,state FROM turns WHERE branch_id=? ORDER BY created_ms DESC LIMIT 200",
                    (selected,),
                ),
                "snapshotCursor": cursor,
                "activities": activities,
            }

        return await self.db.call(read)

    async def accept(self, owner, cid, request_key, text, attachment_ids=None):
        attachment_ids = attachment_ids or []
        if (
            not request_key
            or (not text.strip() and not attachment_ids)
            or len(text) > 100_000
            or len(attachment_ids) > 6
            or len(set(attachment_ids)) != len(attachment_ids)
        ):
            raise DomainError("INVALID_MESSAGE")
        payload = {"conversation": cid, "text": text}
        if attachment_ids:
            payload["attachmentIds"] = attachment_ids
        digest = hashlib.sha256(encoded(payload).encode()).hexdigest()

        def write(db):
            c = owned(db, owner, cid)
            old = row(
                db,
                "SELECT * FROM requests WHERE owner_id=? AND request_key=?",
                (owner, request_key),
            )
            if old:
                if old["payload_sha256"] != digest:
                    raise DomainError("REQUEST_KEY_CONFLICT", 409)
                accepted = row(
                    db,
                    "SELECT id FROM messages WHERE turn_id=? AND role='user' ORDER BY seq LIMIT 1",
                    (old["turn_id"],),
                )
                receipt = row(db, "SELECT id FROM events WHERE event_key=?", (old["id"],))
                return {
                    "turnId": old["turn_id"],
                    "requestId": old["id"],
                    "messageId": accepted["id"] if accepted else None,
                    "cursor": receipt["id"] if receipt else None,
                    "reused": True,
                }
            rid, tid = identity(), identity()
            db.execute(
                "INSERT INTO requests(id,owner_id,request_key,payload_sha256,conversation_id,"
                "accepted_ms) VALUES(?,?,?,?,?,?)",
                (rid, owner, request_key, digest, cid, now_ms()),
            )
            db.execute(
                "INSERT INTO turns(id,request_id,conversation_id,branch_id,trigger_kind,state,"
                "created_ms) VALUES(?,?,?,?,?,'queued',?)",
                (tid, rid, cid, c["active_branch_id"], "user", now_ms()),
            )
            db.execute("UPDATE requests SET turn_id=? WHERE id=?", (tid, rid))
            mid = message(db, cid, c["active_branch_id"], "user", {"text": text}, turn_id=tid)
            if attachment_ids:
                references = Attachments.bind(db, owner, mid, attachment_ids)
                db.execute(
                    "UPDATE messages SET content_json=? WHERE id=?",
                    (encoded({"text": text, "attachments": references}), mid),
                )
            remember_request(db, owner, cid, mid, text)
            db.execute(
                "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms)"
                " VALUES(?,'turn.run',?,?,?,'queued',?)",
                (identity(), tid, tid, "{}", now_ms()),
            )
            cursor = event(
                db,
                cid,
                "message.accepted",
                {"turnId": tid, "messageId": mid},
                key=rid,
                turn_id=tid,
                message_id=mid,
            )
            db.execute(
                "UPDATE conversations SET title=CASE WHEN title='New conversation' THEN ? ELSE title END,updated_ms=? WHERE id=?",
                (
                    (
                        text.strip()
                        or (references[0]["name"] if attachment_ids else "New conversation")
                    )[:80],
                    now_ms(),
                    cid,
                ),
            )
            return {"turnId": tid, "requestId": rid, "messageId": mid, "cursor": cursor}

        return await self.db.call(write, write=True)

    async def fork(self, owner, cid, message_id):
        def write(db):
            c = owned(db, owner, cid)
            source = history(db, c["active_branch_id"])
            cut = next((m for m in source if m["id"] == message_id), None)
            if (
                not cut
                or cut["role"] != "assistant"
                or cut["status"] != "completed"
                or json.loads(cut["content_json"]).get("tool_calls")
            ):
                raise DomainError("FORK_REQUIRES_COMPLETED_ROUND", 409)
            if cut["turn_id"] and row(
                db, "SELECT id FROM turns WHERE id=? AND state!='completed'", (cut["turn_id"],)
            ):
                raise DomainError("FORK_REQUIRES_COMPLETED_ROUND", 409)
            if row(
                db,
                "SELECT id FROM turns WHERE branch_id=? AND state IN ('queued','running')",
                (c["active_branch_id"],),
            ):
                raise DomainError("BRANCH_BUSY", 409)
            bid = identity()
            db.execute(
                "INSERT INTO branches(id,conversation_id,parent_branch_id,fork_message_id,"
                "created_ms) VALUES(?,?,?,?,?)",
                (bid, cid, cut["branch_id"], cut["id"], now_ms()),
            )
            db.execute(
                "UPDATE conversations SET active_branch_id=?,updated_ms=? WHERE id=?",
                (bid, now_ms(), cid),
            )
            event(db, cid, "conversation.forked", {"branchId": bid, "messageId": message_id})
            return {"branchId": bid}

        return await self.db.call(write, write=True)

    async def events(self, owner, cid, cursor=0):
        def read(db):
            owned(db, owner, cid)
            batch = [
                dict(e, payload=json.loads(e["payload_json"]))
                for e in rows(
                    db,
                    "SELECT e.*,CASE WHEN k.origin_conversation_id=e.conversation_id THEN k.origin_branch_id ELSE COALESCE(m.branch_id,t.branch_id,k.origin_branch_id) END AS branchId "
                    "FROM events e LEFT JOIN messages m ON m.id=e.message_id LEFT JOIN turns t ON t.id=e.turn_id "
                    "LEFT JOIN tasks k ON k.id=e.task_id WHERE e.conversation_id=? AND e.id>? ORDER BY e.id LIMIT 100",
                    (cid, cursor),
                )
            ]
            visible_by_branch = {}
            for item in batch:
                activity = item["payload"].get("activity")
                if not activity or "preview" not in activity:
                    continue
                branch = item["branchId"]
                if branch not in visible_by_branch:
                    visible_by_branch[branch] = {
                        entry["id"] for entry in conversation_activity(db, cid, history(db, branch))
                    }
                if activity["id"] not in visible_by_branch[branch]:
                    item["payload"].pop("activity")
            return batch

        return await self.db.call(read)

    async def recover(self):
        def write(db):
            for turn in rows(db, "SELECT * FROM turns WHERE state='running'"):
                db.execute(
                    "UPDATE turns SET state='interrupted',finished_ms=? WHERE id=?",
                    (now_ms(), turn["id"]),
                )
                db.execute(
                    "UPDATE messages SET status='interrupted' WHERE turn_id=? AND status='streaming'",
                    (turn["id"],),
                )
                db.execute(
                    "UPDATE jobs SET state='failed' WHERE kind='turn.run' AND aggregate_id=?",
                    (turn["id"],),
                )
                event(
                    db,
                    turn["conversation_id"],
                    "turn.interrupted",
                    {"turnId": turn["id"], "reason": "runtime_restart"},
                    turn_id=turn["id"],
                )
            db.execute("UPDATE tool_calls SET state='unknown' WHERE state IN ('planned','running')")
            db.execute(
                "UPDATE jobs SET state='queued' WHERE state='running' AND kind='context.compact'"
            )

        await self.db.call(write, write=True)
