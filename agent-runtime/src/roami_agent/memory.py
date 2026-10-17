"""Scoped, source-backed memories with CJK-aware FTS and logical deletion."""

import hashlib
import re

from .conversation import owned
from .storage import DomainError, encoded, event, identity, now_ms, row, rows


def search_tokens(text: str) -> str:
    words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    for sequence in re.findall(r"[\u3400-\u9fff]+", text):
        words.extend(sequence)
        words.extend(sequence[i : i + 2] for i in range(len(sequence) - 1))
    return " ".join(dict.fromkeys(words))


class Memories:
    def __init__(self, database):
        self.db = database

    async def save(
        self,
        owner,
        title,
        body,
        source_message_id,
        *,
        kind="fact",
        project_id=None,
        conversation_id=None,
        task_id=None,
        day_key=None,
    ):
        if (
            not body.strip()
            or len(body) > 20_000
            or kind not in {"fact", "decision", "preference", "summary"}
        ):
            raise DomainError("INVALID_MEMORY")

        def write(db):
            source = row(
                db,
                "SELECT m.*,c.owner_id FROM messages m JOIN conversations c "
                "ON c.id=m.conversation_id WHERE m.id=? AND c.owner_id=? AND m.deleted_ms IS NULL",
                (source_message_id, owner),
            )
            if not source:
                raise DomainError("MEMORY_SOURCE_NOT_FOUND", 404)
            if conversation_id:
                owned(db, owner, conversation_id)
            if task_id and not row(
                db, "SELECT id FROM tasks WHERE id=? AND owner_id=?", (task_id, owner)
            ):
                raise DomainError("TASK_NOT_FOUND", 404)
            key = hashlib.sha256(
                encoded([kind, project_id, conversation_id, task_id, title]).encode()
            ).hexdigest()
            fingerprint = hashlib.sha256(source["content_json"].encode()).hexdigest()
            if row(
                db,
                "SELECT 1 FROM memory_tombstones WHERE owner_id=? AND source_fingerprint=? "
                "AND canonical_key=?",
                (owner, fingerprint, key),
            ):
                raise DomainError("MEMORY_FORGOTTEN", 409)
            old = row(
                db,
                "SELECT * FROM memory_records WHERE owner_id=? AND canonical_key=? "
                "AND state='active'",
                (owner, key),
            )
            if old and old["body"] == body:
                return old
            ident, timestamp = identity(), now_ms()
            if old:
                db.execute(
                    "UPDATE memory_records SET state='superseded',updated_ms=? WHERE id=?",
                    (timestamp, old["id"]),
                )
            db.execute(
                "INSERT INTO memory_records(id,owner_id,kind,project_id,conversation_id,task_id,"
                "day_key,timezone,title,body,search_tokens,canonical_key,state,revision,supersedes_id,"
                "valid_from_ms,created_ms,updated_ms) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ident,
                    owner,
                    kind,
                    project_id,
                    conversation_id,
                    task_id,
                    day_key,
                    "UTC" if day_key else None,
                    title[:200],
                    body,
                    search_tokens(title + " " + body),
                    key,
                    "active",
                    old["revision"] + 1 if old else 1,
                    old["id"] if old else None,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            db.execute(
                "INSERT INTO memory_sources(memory_id,source_key,message_id,source_sha256) VALUES(?,?,?,?)",
                (ident, source_message_id, source_message_id, fingerprint),
            )
            db.execute(
                "UPDATE owner_versions SET memory_epoch=memory_epoch+1 WHERE owner_id=?", (owner,)
            )
            return row(db, "SELECT * FROM memory_records WHERE id=?", (ident,))

        return await self.db.call(write, write=True)

    async def get(self, owner, memory_id):
        def read(db):
            memory = row(
                db,
                "SELECT * FROM memory_records WHERE id=? AND owner_id=? AND state='active' "
                "AND (expires_ms IS NULL OR expires_ms>?)",
                (memory_id, owner, now_ms()),
            )
            if not memory:
                raise DomainError("MEMORY_NOT_FOUND", 404)
            memory["sources"] = rows(
                db, "SELECT * FROM memory_sources WHERE memory_id=?", (memory_id,)
            )
            return memory

        return await self.db.call(read)

    async def search(
        self,
        owner,
        query="",
        *,
        conversation_id=None,
        project_id=None,
        task_id=None,
        day_key=None,
        limit=20,
    ):
        def read(db):
            if conversation_id:
                owned(db, owner, conversation_id)
            conditions = [
                "r.owner_id=?",
                "r.state='active'",
                "(r.expires_ms IS NULL OR r.expires_ms>?)",
            ]
            args = [owner, now_ms()]
            for column, value in [
                ("conversation_id", conversation_id),
                ("project_id", project_id),
                ("task_id", task_id),
                ("day_key", day_key),
            ]:
                if value is not None:
                    conditions.append(f"r.{column}=?")
                    args.append(value)
            join = ""
            tokens = search_tokens(query).split()[:24]
            if query.strip() and not tokens:
                return []
            if tokens:
                join = " JOIN memory_fts f ON f.record_id=r.id"
                conditions.append("memory_fts MATCH ?")
                args.append(" AND ".join('"' + token + '"' for token in tokens))
            return rows(
                db,
                "SELECT r.* FROM memory_records r"
                + join
                + " WHERE "
                + " AND ".join(conditions)
                + " ORDER BY r.updated_ms DESC LIMIT ?",
                (*args, min(max(limit, 1), 100)),
            )

        return await self.db.call(read)

    async def forget(self, owner, memory_id):
        def write(db):
            memory = row(
                db, "SELECT * FROM memory_records WHERE id=? AND owner_id=?", (memory_id, owner)
            )
            if not memory:
                raise DomainError("MEMORY_NOT_FOUND", 404)
            for source in rows(
                db, "SELECT source_sha256 FROM memory_sources WHERE memory_id=?", (memory_id,)
            ):
                db.execute(
                    "INSERT OR IGNORE INTO memory_tombstones VALUES(?,?,?,?)",
                    (owner, source["source_sha256"], memory["canonical_key"] or "", now_ms()),
                )
            db.execute(
                "INSERT OR IGNORE INTO context_omissions(owner_id,message_id,source_memory_id,reason,created_ms) "
                "SELECT ?,message_id,?,'forgotten_memory',? FROM memory_sources WHERE memory_id=? AND message_id IS NOT NULL",
                (owner, memory_id, now_ms(), memory_id),
            )
            db.execute(
                "UPDATE memory_records SET state='deleted',updated_ms=? WHERE id=?",
                (now_ms(), memory_id),
            )
            db.execute(
                "UPDATE owner_versions SET memory_epoch=memory_epoch+1 WHERE owner_id=?", (owner,)
            )
            db.execute(
                "UPDATE context_snapshots SET state='invalid' WHERE branch_id IN "
                "(SELECT b.id FROM branches b JOIN conversations c ON b.conversation_id=c.id "
                "WHERE c.owner_id=?)",
                (owner,),
            )
            if memory["conversation_id"]:
                event(db, memory["conversation_id"], "memory.forgotten", {"memoryId": memory_id})
            return {"memoryId": memory_id, "state": "deleted"}

        return await self.db.call(write, write=True)
