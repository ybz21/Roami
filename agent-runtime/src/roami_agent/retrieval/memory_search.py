"""Scoped FTS candidates, bounded single-character fallback and source-backed evidence."""

import re
import time

from roami_agent.protocol.identity import now_ms
from roami_agent.retrieval.tokens import search_tokens
from roami_agent.storage.database import row, rows
from roami_agent.storage.transcript_repository import owned

FORGOTTEN_PROMOTED_PREFERENCE = (
    "EXISTS (SELECT 1 FROM memory_edges p JOIN memory_records g ON g.id=p.derived_id "
    "JOIN context_omissions o ON o.source_memory_id=g.id AND o.owner_id=r.owner_id "
    "JOIN memory_sources s ON s.memory_id=r.id AND s.message_id=o.message_id "
    "WHERE p.parent_id=r.id AND r.kind='preference' AND g.kind='preference' "
    "AND g.owner_id=r.owner_id AND g.conversation_id IS NULL AND g.project_id IS NULL "
    "AND g.task_id IS NULL)"
)

TOKENIZER_VERSION = "cjk-bigram-v2"
RANKING_VERSION = "fts-scope-v1"


class MemorySearch:
    def __init__(self, database):
        self.db = database

    async def recall(self, owner, query="", **scope):
        started = time.monotonic()
        result = await self._search(owner, query, **scope)
        return {
            **result,
            "tookMs": round((time.monotonic() - started) * 1000, 2),
            "tokenizerVersion": TOKENIZER_VERSION,
            "rankingVersion": RANKING_VERSION,
        }

    async def search(self, owner, query="", **scope):
        return (await self._search(owner, query, **scope))["hits"]

    async def _search(
        self,
        owner,
        query="",
        *,
        conversation_id=None,
        project_id=None,
        task_id=None,
        day_key=None,
        timezone=None,
        limit=20,
        include_global=False,
        kind=None,
    ):
        limit = min(max(limit, 1), 100)
        query = query[:1000]

        def read(db):
            if conversation_id:
                owned(db, owner, conversation_id)
            timestamp = now_ms()
            conditions = [
                "r.owner_id=?",
                "r.state='active'",
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
            args = [owner, timestamp, timestamp, timestamp]
            if kind is not None:
                if kind not in {"fact", "decision", "preference", "summary"}:
                    from roami_agent.protocol.errors import DomainError

                    raise DomainError("INVALID_MEMORY_KIND")
                conditions.append("r.kind=?")
                args.append(kind)
            scopes, scope_args = [], []
            for column, value in [
                ("conversation_id", conversation_id),
                ("project_id", project_id),
                ("task_id", task_id),
                ("day_key", day_key),
                ("timezone", timezone),
            ]:
                if value is not None:
                    scopes.append(f"r.{column}=?")
                    scope_args.append(value)
            if day_key is None:
                scopes.append("r.day_key IS NULL")
            predicate = " AND ".join(scopes) or "1=1"
            if include_global and day_key is None:
                predicate = (
                    "("
                    + predicate
                    + ") OR (r.kind='preference' AND r.project_id IS NULL AND r.conversation_id IS NULL AND r.task_id IS NULL AND r.day_key IS NULL)"
                )
            conditions.append("(" + predicate + ")")
            args.extend(scope_args)
            where = " AND ".join(conditions)
            tokens = search_tokens(query).split()[:24]
            single = bool(re.fullmatch(r"[\u3400-\u9fff]", query.strip()))
            if single:
                candidates = rows(
                    db,
                    "SELECT r.* FROM memory_records r WHERE "
                    + where
                    + " ORDER BY r.updated_ms DESC,r.id LIMIT 500",
                    args,
                )
                candidates = [
                    item for item in candidates if query.strip() in item["title"] + item["body"]
                ]
                reason = "scoped_recent_character"
            elif tokens:
                candidates = rows(
                    db,
                    "SELECT r.*,bm25(memory_fts) AS fts_rank FROM memory_fts JOIN memory_records r ON r.id=memory_fts.record_id WHERE "
                    + where
                    + " AND memory_fts MATCH ? ORDER BY fts_rank,r.updated_ms DESC,r.id LIMIT ?",
                    (*args, " OR ".join('"' + token + '"' for token in tokens), max(40, limit + 1)),
                )
                reason = "scoped_fts"
            elif query.strip():
                candidates = []
                reason = "no_literal_tokens"
            else:
                candidates = rows(
                    db,
                    "SELECT r.* FROM memory_records r WHERE "
                    + where
                    + " ORDER BY r.updated_ms DESC,r.id LIMIT ?",
                    (*args, limit + 1),
                )
                reason = "scoped_recent"
            hits, seen = [], set()
            for item in candidates:
                canonical = item["canonical_key"] or item["id"]
                if canonical in seen:
                    continue
                seen.add(canonical)
                item.update(
                    sourceRefs=rows(
                        db,
                        "SELECT source_key,message_id,event_id,artifact_id,source_sha256 FROM memory_sources WHERE memory_id=? ORDER BY source_key LIMIT 64",
                        (item["id"],),
                    ),
                    rankReason=reason,
                    tokenEstimate=len(item["body"].encode()),
                    scope={
                        key: item[key]
                        for key in [
                            "conversation_id",
                            "project_id",
                            "task_id",
                            "day_key",
                            "timezone",
                        ]
                    },
                )
                hits.append(item)
                if len(hits) > limit:
                    break
            version = row(db, "SELECT memory_epoch FROM owner_versions WHERE owner_id=?", (owner,))
            return {
                "memoryEpoch": version["memory_epoch"] if version else 1,
                "hits": hits[:limit],
                "truncated": len(hits) > limit,
            }

        return await self.db.call(read)
