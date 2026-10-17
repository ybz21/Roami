"""Append-only conversation branches, idempotent intake, and committed event replay."""

import hashlib
import json

from .storage import Database, DomainError, encoded, event, identity, now_ms, row, rows


def owned(db, owner: str, conversation_id: str):
    result = row(
        db,
        "SELECT * FROM conversations WHERE id=? AND owner_id=? AND deleted_ms IS NULL",
        (conversation_id, owner),
    )
    if not result:
        raise DomainError("CONVERSATION_NOT_FOUND", 404)
    return result


def message(
    db,
    conversation_id,
    branch_id,
    role,
    content,
    *,
    turn_id=None,
    status="completed",
    message_id=None,
):
    seq = db.execute(
        "UPDATE branches SET head_seq=head_seq+1 WHERE id=? RETURNING head_seq", (branch_id,)
    ).fetchone()[0]
    ident = message_id or identity()
    db.execute(
        "INSERT INTO messages(id,conversation_id,branch_id,seq,turn_id,role,content_json,"
        "status,created_ms) VALUES(?,?,?,?,?,?,?,?,?)",
        (ident, conversation_id, branch_id, seq, turn_id, role, encoded(content), status, now_ms()),
    )
    db.execute("UPDATE conversations SET updated_ms=? WHERE id=?", (now_ms(), conversation_id))
    return ident


def history(db, branch_id, *, through=None, depth=0):
    if depth > 16:
        raise DomainError("BRANCH_DEPTH_EXCEEDED")
    branch = row(db, "SELECT * FROM branches WHERE id=?", (branch_id,))
    if not branch:
        raise DomainError("BRANCH_NOT_FOUND", 404)
    prefix = []
    if branch["parent_branch_id"]:
        cut = row(db, "SELECT seq FROM messages WHERE id=?", (branch["fork_message_id"],))
        prefix = history(db, branch["parent_branch_id"], through=cut["seq"], depth=depth + 1)
    suffix = rows(
        db,
        "SELECT * FROM messages WHERE branch_id=? AND seq<=? AND deleted_ms IS NULL "
        "AND status!='deleted' ORDER BY seq",
        (branch_id, branch["head_seq"] if through is None else through),
    )
    return prefix + suffix


class Conversations:
    def __init__(self, database: Database):
        self.db = database

    async def create(self, owner: str, title="New conversation"):
        def write(db):
            cid, bid = identity(), identity()
            db.execute("INSERT OR IGNORE INTO owner_versions(owner_id) VALUES(?)", (owner,))
            db.execute(
                "INSERT INTO conversations(id,owner_id,title,created_ms,updated_ms) "
                "VALUES(?,?,?,?,?)",
                (cid, owner, title[:200], now_ms(), now_ms()),
            )
            db.execute(
                "INSERT INTO branches(id,conversation_id,created_ms) VALUES(?,?,?)",
                (bid, cid, now_ms()),
            )
            db.execute("UPDATE conversations SET active_branch_id=? WHERE id=?", (bid, cid))
            event(db, cid, "conversation.created", {"conversationId": cid, "branchId": bid})
            return owned(db, owner, cid)

        return await self.db.call(write, write=True)

    async def list(self, owner):
        return await self.db.call(
            lambda db: rows(
                db,
                "SELECT * FROM conversations WHERE owner_id=? "
                "AND deleted_ms IS NULL ORDER BY updated_ms DESC LIMIT 200",
                (owner,),
            )
        )

    async def get(self, owner, cid):
        return await self.db.call(lambda db: owned(db, owner, cid))

    async def messages(self, owner, cid):
        def read(db):
            c = owned(db, owner, cid)
            result = history(db, c["active_branch_id"])
            cursor = db.execute(
                "SELECT COALESCE(MAX(id),0) FROM events WHERE conversation_id=?", (cid,)
            ).fetchone()[0]
            return {
                "conversation": c,
                "messages": [dict(m, content=json.loads(m["content_json"])) for m in result],
                "snapshotCursor": cursor,
            }

        return await self.db.call(read)

    async def accept(self, owner, cid, request_key, text):
        if not request_key or not text.strip() or len(text) > 100_000:
            raise DomainError("INVALID_MESSAGE")
        digest = hashlib.sha256(encoded({"conversation": cid, "text": text}).encode()).hexdigest()

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
                return {"turnId": old["turn_id"], "requestId": old["id"], "reused": True}
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
            return [
                dict(e, payload=json.loads(e["payload_json"]))
                for e in rows(
                    db,
                    "SELECT * FROM events WHERE conversation_id=? AND id>? ORDER BY id LIMIT 100",
                    (cid, cursor),
                )
            ]

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
