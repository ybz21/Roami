"""Read bounded source quotations without exposing missing or foreign sources."""

import json

from roami_agent.memory.writer import source_snapshot
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row, rows


def read_evidence(db, owner, record):
    result = []
    for ref in rows(
        db,
        "SELECT * FROM memory_sources WHERE memory_id=? ORDER BY source_key LIMIT 16",
        (record["id"],),
    ):
        try:
            source = source_snapshot(db, owner, ref["source_key"])
            content = json.loads(source["content_json"])
            if isinstance(content, list):
                payload = json.loads(content[1])
                text = (payload.get("result") or {}).get("summary") or payload.get("summary") or ""
            else:
                text = content.get("text", "")
            result.append(
                {
                    "sourceKey": ref["source_key"],
                    "sha256": ref["source_sha256"],
                    "unchanged": source["sha256"] == ref["source_sha256"],
                    "available": True,
                    "conversationId": source["conversation_id"] or record["conversation_id"],
                    "branchId": source.get("branch_id")
                    or (
                        row(
                            db,
                            "SELECT active_branch_id FROM conversations WHERE id=? AND owner_id=?",
                            (source["conversation_id"] or record["conversation_id"], owner),
                        )
                        or {}
                    ).get("active_branch_id"),
                    "messageId": source.get("message_id"),
                    "text": str(text)[:4000],
                    "truncated": len(str(text)) > 4000,
                    "kind": source.get("kind", "message"),
                    "role": source.get("role"),
                    "conversationTitle": (
                        row(
                            db,
                            "SELECT title FROM conversations WHERE id=? AND owner_id=? AND deleted_ms IS NULL",
                            (source["conversation_id"], owner),
                        )
                        or {}
                    ).get("title"),
                    "createdMs": source["created_ms"],
                }
            )
        except DomainError:
            result.append({"sourceKey": ref["source_key"], "available": False})
    return result
