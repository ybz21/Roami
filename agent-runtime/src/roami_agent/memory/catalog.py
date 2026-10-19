"""Owner-wide memory management without changing recall scope or deduplicating records."""

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.retrieval.memory_search import FORGOTTEN_PROMOTED_PREFERENCE
from roami_agent.storage.database import row, rows
from roami_agent.storage.transcript_repository import owned


class MemoryCatalog:
    def __init__(self, database):
        self.db = database

    async def list(
        self,
        owner,
        *,
        query="",
        state="active",
        conversation_id=None,
        project_id=None,
        task_id=None,
        day_key=None,
        timezone=None,
        kind=None,
        personal_only=False,
        category="all",
        limit=20,
        offset=0,
    ):
        if state not in {"active", "candidate", "conflict"}:
            raise DomainError("INVALID_MEMORY_STATE")
        if category not in {"all", "knowledge", "activity"}:
            raise DomainError("INVALID_MEMORY_CATEGORY")
        limit, offset = min(max(limit, 1), 100), max(offset, 0)

        def read(db):
            if conversation_id:
                owned(db, owner, conversation_id)
            conditions, args = ["r.owner_id=?", "r.state=?"], [owner, state]
            for column, value in [
                ("conversation_id", conversation_id),
                ("project_id", project_id),
                ("task_id", task_id),
                ("day_key", day_key),
                ("timezone", timezone),
                ("kind", kind),
            ]:
                if value is not None:
                    conditions.append(f"r.{column}=?")
                    args.append(value)
            if category != "all":
                conditions.append(
                    "r.day_key IS " + ("NOT NULL" if category == "activity" else "NULL")
                )
            if personal_only:
                conditions.extend(
                    f"r.{column} IS NULL"
                    for column in ("conversation_id", "project_id", "task_id", "day_key")
                )
            if state == "active":
                conditions.extend(
                    [
                        "r.valid_from_ms<=?",
                        "(r.valid_until_ms IS NULL OR r.valid_until_ms>?)",
                        "(r.expires_ms IS NULL OR r.expires_ms>?)",
                        "NOT " + FORGOTTEN_PROMOTED_PREFERENCE,
                        (
                            "NOT EXISTS (SELECT 1 FROM memory_sources s LEFT JOIN artifacts a ON a.id=s.artifact_id "
                            "WHERE s.memory_id=r.id AND s.artifact_id IS NOT NULL "
                            "AND (a.id IS NULL OR a.deleted_ms IS NOT NULL OR a.owner_id!=r.owner_id))"
                        ),
                    ]
                )
                args.extend([now_ms()] * 3)
            if query.strip():
                literal = (
                    "%"
                    + query.strip()[:1000]
                    .replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_")
                    + "%"
                )
                conditions.append("(r.title LIKE ? ESCAPE '\\' OR r.body LIKE ? ESCAPE '\\')")
                args.extend([literal, literal])
            where = " AND ".join(conditions)
            total = row(db, "SELECT COUNT(*) AS total FROM memory_records r WHERE " + where, args)[
                "total"
            ]
            ordering = (
                "r.day_key DESC,r.updated_ms DESC,r.id"
                if category == "activity"
                else "r.updated_ms DESC,r.id"
            )
            items = rows(
                db,
                "SELECT r.*,c.title AS conversation_title,json_extract(t.intent_json,'$.goal') AS task_title,"
                "(SELECT COUNT(*) FROM memory_sources s WHERE s.memory_id=r.id) AS source_count "
                "FROM memory_records r LEFT JOIN conversations c ON c.id=r.conversation_id AND c.owner_id=r.owner_id "
                "LEFT JOIN tasks t ON t.id=r.task_id AND t.owner_id=r.owner_id "
                "WHERE " + where + " ORDER BY " + ordering + " LIMIT ? OFFSET ?",
                (*args, limit, offset),
            )
            return {"items": items, "total": total, "offset": offset, "limit": limit}

        return await self.db.call(read)
