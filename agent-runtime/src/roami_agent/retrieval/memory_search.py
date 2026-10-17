from roami_agent.protocol.identity import now_ms
from roami_agent.retrieval.tokens import search_tokens
from roami_agent.storage.database import rows
from roami_agent.storage.transcript_repository import owned


class MemorySearch:
    def __init__(self, database):
        self.db = database

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
