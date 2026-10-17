"Scoped, source-backed memories with CJK-aware FTS and logical deletion."

import json

from roami_agent.memory.daily import DailyMemories
from roami_agent.memory.provenance import seed_dependencies
from roami_agent.memory.writer import commit_memory, source_snapshot
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.retrieval.memory_search import MemorySearch
from roami_agent.storage.database import event, row, rows
from roami_agent.storage.transcript_repository import owned


class Memories:
    def __init__(self, database, timezone_name="UTC"):
        self.db = database
        self.retrieval = MemorySearch(database)
        self.search = self.retrieval.search
        self.recall = self.retrieval.recall
        self.daily = DailyMemories(database, timezone_name)

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
        return await self.db.call(
            lambda db: commit_memory(
                db,
                owner,
                title,
                body,
                [source_message_id],
                kind=kind,
                project_id=project_id,
                conversation_id=conversation_id,
                task_id=task_id,
                day_key=day_key,
                timezone="UTC" if day_key else None,
                confirmed=True,
            ),
            write=True,
        )

    async def propose(self, owner, title, body, source_ids, *, expected_sources, **scope):
        return await self.db.call(
            lambda db: commit_memory(
                db, owner, title, body, source_ids, expected_sources=expected_sources, **scope
            ),
            write=True,
        )

    async def get(self, owner, memory_id):
        def read(db):
            memory = row(
                db,
                "SELECT * FROM memory_records WHERE id=? AND owner_id=? AND state='active' "
                "AND valid_from_ms<=? AND (valid_until_ms IS NULL OR valid_until_ms>?) "
                "AND (expires_ms IS NULL OR expires_ms>?)",
                (memory_id, owner, now_ms(), now_ms(), now_ms()),
            )
            if not memory:
                raise DomainError("MEMORY_NOT_FOUND", 404)
            if row(
                db,
                "SELECT 1 FROM memory_sources s LEFT JOIN artifacts a ON a.id=s.artifact_id "
                "WHERE s.memory_id=? AND s.artifact_id IS NOT NULL "
                "AND (a.id IS NULL OR a.deleted_ms IS NOT NULL OR a.owner_id!=?)",
                (memory_id, owner),
            ):
                raise DomainError("MEMORY_SOURCE_NOT_FOUND", 404)
            memory["sources"] = rows(
                db, "SELECT * FROM memory_sources WHERE memory_id=?", (memory_id,)
            )
            return memory

        return await self.db.call(read)

    async def candidates(
        self,
        owner,
        *,
        conversation_id=None,
        project_id=None,
        task_id=None,
        day_key=None,
        timezone=None,
        kind=None,
        query="",
        state="candidate",
        limit=20,
    ):
        if state not in {"candidate", "conflict"}:
            raise DomainError("INVALID_MEMORY_STATE")

        def read(db):
            if conversation_id:
                owned(db, owner, conversation_id)
            conditions = ["owner_id=?", "state=?"]
            args = [owner, state]
            for column, value in [
                ("conversation_id", conversation_id),
                ("project_id", project_id),
                ("task_id", task_id),
                ("day_key", day_key),
                ("timezone", timezone),
                ("kind", kind),
            ]:
                if value is not None:
                    conditions.append(column + "=?")
                    args.append(value)
            if query:
                literal = (
                    "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                )
                conditions.append("(title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')")
                args.extend([literal, literal])
            result = rows(
                db,
                "SELECT * FROM memory_records WHERE "
                + " AND ".join(conditions)
                + " ORDER BY created_ms DESC,id LIMIT ?",
                (*args, min(max(limit, 1), 100)),
            )
            for item in result:
                item["sourceRefs"] = rows(
                    db,
                    "SELECT * FROM memory_sources WHERE memory_id=? ORDER BY source_key LIMIT 64",
                    (item["id"],),
                )
            return result

        return await self.db.call(read)

    async def evidence(self, owner, memory_id):
        def read(db):
            record = row(
                db,
                "SELECT * FROM memory_records WHERE owner_id=? AND id=? AND state IN ('active','candidate','conflict')",
                (owner, memory_id),
            )
            if not record:
                raise DomainError("MEMORY_NOT_FOUND", 404)
            result = []
            for ref in rows(
                db,
                "SELECT * FROM memory_sources WHERE memory_id=? ORDER BY source_key LIMIT 16",
                (memory_id,),
            ):
                try:
                    source = source_snapshot(db, owner, ref["source_key"])
                    content = json.loads(source["content_json"])
                    if isinstance(content, list):
                        payload = json.loads(content[1])
                        text = (
                            (payload.get("result") or {}).get("summary")
                            or payload.get("summary")
                            or ""
                        )
                    else:
                        text = content.get("text", "")
                    result.append(
                        {
                            "sourceKey": ref["source_key"],
                            "sha256": ref["source_sha256"],
                            "unchanged": source["sha256"] == ref["source_sha256"],
                            "conversationId": record["conversation_id"]
                            or source["conversation_id"],
                            "text": str(text)[:4000],
                            "kind": source.get("kind", "message"),
                            "createdMs": source["created_ms"],
                        }
                    )
                except DomainError:
                    result.append({"sourceKey": ref["source_key"], "available": False})
            return result

        return await self.db.call(read)

    async def confirm(self, owner, memory_id, accepted=True):
        if not accepted:
            return await self.forget(owner, memory_id, forget_sources=False, candidate_only=True)

        def write(db):
            candidate = row(
                db,
                "SELECT * FROM memory_records WHERE owner_id=? AND id=?",
                (owner, memory_id),
            )
            if not candidate:
                raise DomainError("MEMORY_CANDIDATE_NOT_FOUND", 404)
            if candidate["state"] not in {"candidate", "conflict"}:
                active = row(
                    db,
                    "SELECT * FROM memory_records WHERE owner_id=? AND canonical_key=? AND state='active' AND body=?",
                    (owner, candidate["canonical_key"], candidate["body"]),
                )
                if candidate["state"] == "superseded" and active:
                    return active
                raise DomainError("MEMORY_CANDIDATE_ALREADY_RESOLVED", 409)
            sources = rows(db, "SELECT * FROM memory_sources WHERE memory_id=?", (memory_id,))
            result = commit_memory(
                db,
                owner,
                candidate["title"],
                candidate["body"],
                [source["source_key"] for source in sources],
                kind=candidate["kind"],
                project_id=candidate["project_id"],
                conversation_id=candidate["conversation_id"],
                task_id=candidate["task_id"],
                day_key=candidate["day_key"],
                timezone=candidate["timezone"],
                confirmed=True,
                expected_sources={
                    source["source_key"]: source["source_sha256"] for source in sources
                },
                source_watermark=candidate["source_watermark"],
            )
            if candidate["conversation_id"]:
                event(
                    db,
                    candidate["conversation_id"],
                    "memory.confirmed",
                    {"memoryId": result["id"], "candidateId": memory_id},
                )
            return result

        return await self.db.call(write, write=True)

    async def delete(self, owner, memory_id):
        return await self.forget(owner, memory_id, forget_sources=False)

    async def forget(self, owner, memory_id, *, forget_sources=True, candidate_only=False):
        def write(db):
            memory = row(
                db, "SELECT * FROM memory_records WHERE id=? AND owner_id=?", (memory_id, owner)
            )
            if not memory:
                raise DomainError("MEMORY_NOT_FOUND", 404)
            if candidate_only and memory["state"] not in {"candidate", "conflict", "deleted"}:
                raise DomainError("MEMORY_CANDIDATE_ALREADY_RESOLVED", 409)
            for source in rows(
                db, "SELECT source_sha256 FROM memory_sources WHERE memory_id=?", (memory_id,)
            ):
                db.execute(
                    "INSERT OR IGNORE INTO memory_tombstones VALUES(?,?,?,?)",
                    (owner, source["source_sha256"], memory["canonical_key"] or "", now_ms()),
                )
            if forget_sources:
                seed_dependencies(db, owner, memory)
                db.execute(
                    "INSERT OR IGNORE INTO context_omissions(owner_id,message_id,source_memory_id,reason,created_ms) "
                    "SELECT ?,a.message_id,?,'forgotten_artifact',? FROM memory_sources s "
                    "JOIN artifacts a ON a.id=s.artifact_id WHERE s.memory_id=? AND a.message_id IS NOT NULL",
                    (owner, memory_id, now_ms(), memory_id),
                )
                db.execute(
                    "INSERT OR IGNORE INTO context_omissions(owner_id,message_id,source_memory_id,reason,created_ms) "
                    "SELECT ?,message_id,?,'forgotten_memory',? FROM memory_sources WHERE memory_id=? AND message_id IS NOT NULL",
                    (owner, memory_id, now_ms(), memory_id),
                )
                db.execute(
                    "WITH RECURSIVE affected(id) AS ("
                    "SELECT message_id FROM memory_sources WHERE memory_id=? AND message_id IS NOT NULL "
                    "UNION SELECT message_id FROM context_omissions WHERE owner_id=? AND source_memory_id=? "
                    "UNION SELECT k.origin_message_id FROM tasks k JOIN task_attempts r ON r.task_id=k.id "
                    "JOIN messages m ON m.branch_id=r.native_branch_id JOIN affected a ON a.id=m.id WHERE k.owner_id=? "
                    "UNION SELECT k.origin_message_id FROM tasks k JOIN affected a "
                    "ON a.id=json_extract(k.intent_json,'$.sourceAssistantMessageId') WHERE k.owner_id=? "
                    "UNION SELECT k.origin_message_id FROM tasks k JOIN task_attempts r ON r.task_id=k.id "
                    "JOIN tool_calls x ON x.tool_name='delegate' AND r.launch_id IN "
                    "('task:'||k.owner_id||':'||x.idempotency_key, "
                    "'task:'||k.owner_id||':'||substr(x.idempotency_key,instr(x.idempotency_key,':')+1)) "
                    "JOIN affected a ON a.id=x.assistant_message_id WHERE k.owner_id=? "
                    "UNION SELECT k.origin_message_id FROM tasks k JOIN json_each(k.intent_json,'$.sourceMessageIds') j "
                    "JOIN affected a ON a.id=j.value WHERE k.owner_id=? "
                    "UNION SELECT copied.id FROM tasks k JOIN affected a ON a.id=k.origin_message_id "
                    "JOIN task_attempts r ON r.task_id=k.id JOIN messages copied ON copied.branch_id=r.native_branch_id "
                    "WHERE k.owner_id=? AND copied.role='user' "
                    "UNION SELECT reply.id FROM tasks k JOIN affected a ON a.id=k.origin_message_id "
                    "JOIN jobs j ON j.kind='turn.run' AND json_extract(j.payload_json,'$.completion.taskId')=k.id "
                    "JOIN messages reply ON reply.turn_id=j.aggregate_id WHERE k.owner_id=? AND reply.role IN ('assistant','tool') "
                    "UNION SELECT m.id FROM messages m JOIN conversations c ON c.id=m.conversation_id "
                    "JOIN prompt_manifests p ON p.turn_id=m.turn_id JOIN json_each(p.parts_json,'$.sourceMessageIds') j "
                    "JOIN affected a ON a.id=j.value WHERE c.owner_id=? AND m.role IN ('assistant','tool') "
                    "UNION SELECT paired.id FROM messages original JOIN affected a ON a.id=original.id "
                    "JOIN messages paired ON paired.turn_id=original.turn_id "
                    "WHERE original.role IN ('assistant','tool') AND paired.role IN ('assistant','tool')) "
                    "INSERT OR IGNORE INTO context_omissions(owner_id,message_id,source_memory_id,reason,created_ms) "
                    "SELECT ?,id,?,'forgotten_dependency',? FROM affected",
                    (
                        memory_id,
                        owner,
                        memory_id,
                        owner,
                        owner,
                        owner,
                        owner,
                        owner,
                        owner,
                        owner,
                        owner,
                        memory_id,
                        now_ms(),
                    ),
                )
            db.execute(
                "UPDATE memory_records SET state='deleted',updated_ms=? WHERE id=?",
                (now_ms(), memory_id),
            )
            db.execute(
                "WITH RECURSIVE affected(id) AS (SELECT derived_id FROM memory_edges WHERE parent_id=? UNION SELECT e.derived_id FROM memory_edges e JOIN affected a ON e.parent_id=a.id) UPDATE memory_records SET state='candidate',updated_ms=? WHERE id IN (SELECT id FROM affected) AND owner_id=? AND state IN ('active','conflict')",
                (memory_id, now_ms(), owner),
            )
            db.execute(
                "DELETE FROM memory_embeddings WHERE memory_id=? OR memory_id IN (WITH RECURSIVE affected(id) AS (SELECT derived_id FROM memory_edges WHERE parent_id=? UNION SELECT e.derived_id FROM memory_edges e JOIN affected a ON e.parent_id=a.id) SELECT id FROM affected)",
                (memory_id, memory_id),
            )
            if forget_sources:
                invalid = rows(
                    db,
                    "SELECT DISTINCT m.id,m.canonical_key FROM memory_records m JOIN memory_sources s ON s.memory_id=m.id LEFT JOIN events e ON e.id=s.event_id LEFT JOIN tasks t ON t.id=e.task_id WHERE m.owner_id=? AND m.state IN ('candidate','conflict') AND EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=? AND (o.message_id=s.message_id OR o.message_id=t.origin_message_id))",
                    (owner, owner),
                )
                for candidate in invalid:
                    db.execute(
                        "INSERT OR IGNORE INTO memory_tombstones SELECT ?,source_sha256,?,? FROM memory_sources WHERE memory_id=?",
                        (owner, candidate["canonical_key"] or "", now_ms(), candidate["id"]),
                    )
                    db.execute(
                        "UPDATE memory_records SET state='deleted',updated_ms=? WHERE id=?",
                        (now_ms(), candidate["id"]),
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
                event(
                    db,
                    memory["conversation_id"],
                    "memory.forgotten" if forget_sources else "memory.deleted",
                    {"memoryId": memory_id},
                )
            return {"memoryId": memory_id, "state": "deleted"}

        return await self.db.call(write, write=True)
