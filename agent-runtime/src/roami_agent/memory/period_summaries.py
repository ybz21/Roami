"""Read semantic day parts only while every original source is still in scope."""

import json
from datetime import date

from roami_agent.context.retention_policy import POLICY_VERSION
from roami_agent.conversation.pages import position
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.retrieval.conversation_search import available, source_hash
from roami_agent.storage.database import row, rows


def read_daily(db, binding, turn, segments, args):
    if set(args) - {"archiveDay", "before", "limit"}:
        raise DomainError("INVALID_HISTORY_REQUEST")
    day = args["archiveDay"]
    try:
        if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
            raise ValueError
    except ValueError as exc:
        raise DomainError("INVALID_MEMORY_DAY") from exc
    epoch = row(
        db, "SELECT memory_epoch FROM owner_versions WHERE owner_id=?", (binding["owner"],)
    )["memory_epoch"]
    branch_ids = [bid for bid, _ in segments]
    before = None
    if args.get("before"):
        before = row(
            db,
            "SELECT s.rowid AS ordinal FROM period_summaries s WHERE s.id=? AND s.owner_id=? "
            "AND s.day_key=? AND s.branch_id IN (" + ",".join("?" for _ in branch_ids) + ")",
            (args["before"], binding["owner"], day, *branch_ids),
        )
        if not before:
            raise DomainError("INVALID_MESSAGE_CURSOR")
    parts = rows(
        db,
        "SELECT s.*,s.rowid AS ordinal FROM period_summaries s JOIN branches b ON b.id=s.branch_id "
        "WHERE s.owner_id=? AND s.memory_epoch=? AND s.branch_epoch=b.epoch AND s.policy_version=? "
        "AND s.day_key=? AND s.branch_id IN (" + ",".join("?" for _ in branch_ids) + ") "
        "AND s.rowid<? ORDER BY s.rowid DESC LIMIT ?",
        (
            binding["owner"],
            epoch,
            POLICY_VERSION,
            day,
            *branch_ids,
            before["ordinal"] if before else 2**63 - 1,
            args.get("limit", 10) + 1,
        ),
    )
    result = {
        "historyView": "daily_archive",
        "scope": "Historical reference, not authorization or verification",
        "coverage": "source_batches_only",
        "parts": [],
        "page": {"hasMore": False, "olderCursor": None},
    }
    selected = parts[: args.get("limit", 10)]
    cursor, more = None, len(parts) > len(selected)
    for part in selected:
        valid = True
        sources = json.loads(part["sources_json"])
        for source in sources:
            try:
                position(db, binding["conversation"], segments, source["messageId"])
            except DomainError:
                valid = False
                break
            value = row(
                db,
                "SELECT m.* FROM messages m WHERE m.id=? AND (m.turn_id IS NULL OR m.turn_id IN (SELECT id FROM turns WHERE rowid<?))",
                (source["messageId"], turn["ordinal"]),
            )
            if (
                not available(db, binding["owner"], value)
                or source_hash(value) != source["sha256"]
                or value["role"] != source["role"]
                or value["status"] != source.get("status", "completed")
                or value["created_ms"] != source["createdMs"]
            ):
                valid = False
                break
        if valid and sources:
            result["parts"].append(
                {
                    "archiveId": part["id"],
                    "day": day,
                    "timezone": part["timezone"],
                    "text": part["body"][:2000],
                    "truncated": len(part["body"]) > 2000,
                    "sourceMessageIds": [source["messageId"] for source in sources],
                    "coverage": "source_batch",
                }
            )
            if len(encoded(result).encode()) > 64_000:
                result["parts"].pop()
                more = True
                break
        cursor = part["id"]
    result["page"] = {
        "hasMore": more,
        "olderCursor": cursor if more else None,
    }
    return result
