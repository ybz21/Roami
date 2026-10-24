"""Owner-wide browsing with server-side scope, review filtering and pagination."""

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.retrieval.memory_search import FORGOTTEN_PROMOTED_PREFERENCE
from roami_agent.storage.database import row, rows
from roami_agent.storage.transcript_repository import owned

RECORD_JOINS = (
    " FROM memory_records r LEFT JOIN conversations c ON c.id=r.conversation_id "
    "AND c.owner_id=r.owner_id AND c.deleted_ms IS NULL "
    "LEFT JOIN tasks t ON t.id=r.task_id AND t.owner_id=r.owner_id "
)
RECORD_FIELDS = (
    "r.*,c.title AS conversation_title,json_extract(t.intent_json,'$.goal') AS task_title,"
    "(SELECT COUNT(*) FROM memory_sources s WHERE s.memory_id=r.id) AS source_count"
)
ACTIVE = (
    "r.valid_from_ms<=? AND (r.valid_until_ms IS NULL OR r.valid_until_ms>?) "
    "AND (r.expires_ms IS NULL OR r.expires_ms>?) AND NOT "
    + FORGOTTEN_PROMOTED_PREFERENCE
    + " AND NOT EXISTS (SELECT 1 FROM memory_sources s JOIN context_omissions o ON o.message_id=s.message_id AND o.owner_id=r.owner_id WHERE s.memory_id=r.id)"
    + " AND NOT EXISTS (SELECT 1 FROM memory_sources s LEFT JOIN artifacts a ON a.id=s.artifact_id "
    "WHERE s.memory_id=r.id AND s.artifact_id IS NOT NULL "
    "AND (a.id IS NULL OR a.deleted_ms IS NOT NULL OR a.owner_id!=r.owner_id))"
)
SCOPES = {
    "personal": "r.conversation_id IS NULL AND r.project_id IS NULL AND r.task_id IS NULL AND r.day_key IS NULL",
    "project": "r.project_id IS NOT NULL AND r.task_id IS NULL",
    "conversation": "r.conversation_id IS NOT NULL AND r.project_id IS NULL AND r.task_id IS NULL",
    "task": "r.task_id IS NOT NULL",
}


def catalog_conditions(owner, state, category):
    if state not in {"active", "candidate", "conflict", "review"}:
        raise DomainError("INVALID_MEMORY_STATE")
    if category not in {"all", "knowledge", "activity"}:
        raise DomainError("INVALID_MEMORY_CATEGORY")
    conditions, args = (
        [
            "r.owner_id=?",
            "NOT EXISTS (SELECT 1 FROM memory_sources s JOIN context_omissions o ON o.message_id=s.message_id AND o.owner_id=r.owner_id WHERE s.memory_id=r.id)",
        ],
        [owner],
    )
    if state == "review":
        conditions.append("r.state IN ('candidate','conflict')")
    else:
        conditions.append("r.state=?")
        args.append(state)
    if category != "all":
        conditions.append("r.day_key IS " + ("NOT NULL" if category == "activity" else "NULL"))
    if state == "active":
        conditions.append(ACTIVE)
        args.extend([now_ms()] * 3)
    return conditions, args


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
        scope="all",
        limit=20,
        offset=0,
    ):
        conditions, args = catalog_conditions(owner, state, category)
        if scope not in {"all", *SCOPES}:
            raise DomainError("INVALID_MEMORY_SCOPE")
        if kind is not None and kind not in {"fact", "decision", "preference", "summary"}:
            raise DomainError("INVALID_MEMORY_KIND")
        limit, offset = min(max(limit, 1), 100), max(offset, 0)

        def read(db):
            if conversation_id:
                owned(db, owner, conversation_id)
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
            if personal_only:
                conditions.append(SCOPES["personal"])
            if scope != "all":
                conditions.append(SCOPES[scope])
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
                "SELECT "
                + RECORD_FIELDS
                + RECORD_JOINS
                + "WHERE "
                + where
                + " ORDER BY "
                + ordering
                + " LIMIT ? OFFSET ?",
                (*args, limit, offset),
            )
            return {"items": items, "total": total, "offset": offset, "limit": limit}

        return await self.db.call(read)

    async def facets(self, owner, *, state="active", category="knowledge"):
        conditions, args = catalog_conditions(owner, state, category)
        review_conditions, review_args = catalog_conditions(owner, "review", "knowledge")

        def read(db):
            records = rows(
                db,
                "SELECT DISTINCT r.project_id,r.conversation_id,c.title AS conversation_title,r.task_id,json_extract(t.intent_json,'$.goal') AS task_title"
                + RECORD_JOINS
                + "WHERE "
                + " AND ".join(conditions),
                args,
            )
            result = {"project": {}, "conversation": {}, "task": {}}
            for record in records:
                if record["task_id"]:
                    result["task"][record["task_id"]] = record["task_title"]
                elif record["project_id"]:
                    result["project"][record["project_id"]] = None
                elif record["conversation_id"]:
                    result["conversation"][record["conversation_id"]] = record["conversation_title"]
            facets = {
                scope: [{"id": ident, "name": name} for ident, name in values.items()]
                for scope, values in result.items()
            }
            facets["reviewCount"] = row(
                db,
                "SELECT COUNT(*) AS total FROM memory_records r WHERE "
                + " AND ".join(review_conditions),
                review_args,
            )["total"]
            return facets

        return await self.db.call(read)
