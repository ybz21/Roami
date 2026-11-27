"""Rebuildable original-text candidates; the live source remains the read authority."""

import hashlib
import json
import re

from roami_agent.conversation.message_content import LITERAL_CONTENT, message_content
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row, rows
from roami_agent.storage.task_request import task_user_request

STABLE_STATUSES = {"completed", "interrupted", "failed"}


def source_text(value, projection=LITERAL_CONTENT):
    content = json.loads(value["content_json"])
    return projection.human_text(content) if value["role"] == "user" else content.get("text", "")


def source_hash(value):
    content = value["content_json"]
    parsed = json.loads(content)
    if "replyPreview" in parsed:
        parsed.pop("replyPreview")
        content = encoded(parsed)
    return hashlib.sha256(content.encode()).hexdigest()


def terms(text):
    tokens = re.findall(r"[a-zA-Z0-9_]+|[\u3400-\u9fff]", text.lower())
    tokens += [
        sequence[i : i + 2]
        for sequence in re.findall(r"[\u3400-\u9fff]+", text)
        for i in range(len(sequence) - 1)
    ]
    return list(dict.fromkeys(tokens))


def available(db, owner, value):
    if not value or value["status"] not in STABLE_STATUSES or value["deleted_ms"] is not None:
        return False
    if task_user_request(db, value) is None:
        return False
    return not row(
        db,
        "SELECT 1 FROM context_omissions WHERE owner_id=? AND message_id=? UNION ALL "
        "SELECT 1 FROM memory_tombstones WHERE owner_id=? AND source_fingerprint=? LIMIT 1",
        (owner, value["id"], owner, source_hash(value)),
    )


def index_pending(db, limit=32):
    pending = rows(
        db, "SELECT message_id FROM conversation_search_pending ORDER BY rowid LIMIT ?", (limit,)
    )
    for item in pending:
        mid = item["message_id"]
        value = row(db, "SELECT * FROM messages WHERE id=?", (mid,))
        db.execute("DELETE FROM conversation_search_fts WHERE message_id=?", (mid,))
        db.execute("DELETE FROM conversation_search_documents WHERE message_id=?", (mid,))
        if (
            value
            and value["status"] in STABLE_STATUSES
            and value["deleted_ms"] is None
            and value["role"] in {"user", "assistant", "tool"}
        ):
            db.execute(
                "INSERT INTO conversation_search_fts(message_id,terms) VALUES(?,?)",
                (mid, " ".join(terms(source_text(value, message_content(db))))),
            )
            db.execute(
                "INSERT INTO conversation_search_documents(message_id,source_sha256) VALUES(?,?)",
                (mid, source_hash(value)),
            )
        db.execute("DELETE FROM conversation_search_pending WHERE message_id=?", (mid,))
    return len(pending)


def validate_filters(args):
    query = args.get("query", "")
    since, until = args.get("sinceMs"), args.get("untilMs")
    if (
        not isinstance(query, str)
        or len(query) > 1000
        or (query and not terms(query))
        or len(terms(query)) > 64
        or any(
            value is not None and (type(value) is not int or value < 0) for value in [since, until]
        )
        or (since is not None and until is not None and since >= until)
        or args.get("messageId") is not None
        or "offset" in args
    ):
        raise DomainError("INVALID_HISTORY_REQUEST")


def candidates(db, binding, turn, segments, args, index, upper, limit):
    query, since, until = args.get("query", ""), args.get("sinceMs"), args.get("untilMs")
    expression = " AND ".join('"' + token + '"' for token in terms(query))
    selected, pending = [], 0
    for segment_index, (bid, bound) in enumerate(segments):
        if segment_index < index:
            continue
        ceiling = upper if segment_index == index else bound
        conditions = [
            "m.branch_id=?",
            "m.seq<=?",
            "m.deleted_ms IS NULL",
            "m.status IN ('completed','interrupted','failed')",
            "m.role IN ('user','assistant','tool')",
            "NOT EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=? AND o.message_id=m.id)",
            "(m.turn_id IS NULL OR m.turn_id IN (SELECT id FROM turns WHERE rowid<?))",
        ]
        parameters = [bid, ceiling, binding["owner"], turn["ordinal"]]
        if since is not None:
            conditions.append("m.created_ms>=?")
            parameters.append(since)
        if until is not None:
            conditions.append("m.created_ms<?")
            parameters.append(until)
        predicate = " AND ".join(conditions)
        pending += db.execute(
            "SELECT COUNT(*) FROM messages m JOIN conversation_search_pending p ON p.message_id=m.id WHERE "
            + predicate,
            parameters,
        ).fetchone()[0]
        if expression:
            predicate += (
                " AND m.id IN (SELECT message_id FROM conversation_search_fts "
                "WHERE conversation_search_fts MATCH ?)"
            )
            parameters.append(expression)
        if len(selected) < limit:
            selected.extend(
                rows(
                    db,
                    "SELECT m.*,d.source_sha256 AS indexed_sha256 FROM messages m "
                    "LEFT JOIN conversation_search_documents d ON d.message_id=m.id WHERE "
                    + predicate
                    + " ORDER BY m.seq DESC LIMIT ?",
                    (*parameters, limit - len(selected)),
                )
            )
    return selected, {"complete": pending == 0, "pendingMessages": pending}


def match_offset(text, query):
    needles = re.findall(r"[a-zA-Z0-9_]+|[\u3400-\u9fff]+", query.lower())
    hits = [text.lower().find(word) for word in needles]
    return max(0, min((hit for hit in hits if hit >= 0), default=0) - 200)
