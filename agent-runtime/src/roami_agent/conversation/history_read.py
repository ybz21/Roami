"""Read bounded historical evidence without restoring an entire model protocol."""

import json

from roami_agent.conversation.okr_message_context import human_text
from roami_agent.conversation.pages import lineage, position
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row, rows
from roami_agent.storage.task_request import task_user_request

MAX_RESPONSE_BYTES = 64_000
CHUNK_CHARS = 2000
ROLES = {"user", "assistant", "tool"}


def record_content(db, value):
    source = task_user_request(db, value)
    if source is None:
        return None
    content = json.loads(value["content_json"])
    content = {
        key: item
        for key, item in content.items()
        if key in {"text", "tool_calls", "tool_call_id", "taskStatus", "sessionReply", "question"}
    }
    if value["role"] == "user":
        content["text"] = human_text(json.loads(value["content_json"]))
    return encoded(content), source["id"] != value["id"]


def evidence_record(db, value, offset=0):
    content = record_content(db, value)
    if content is None:
        return None
    text, instruction = content
    if offset > len(text):
        raise DomainError("INVALID_MESSAGE_OFFSET")
    end = min(len(text), offset + CHUNK_CHARS)
    return {
        "messageId": value["id"],
        "role": value["role"],
        "status": value["status"],
        "turnId": value["turn_id"],
        "historicalTaskInstruction": instruction,
        "contentFormat": "json",
        "content": text[offset:end],
        "offset": offset,
        "nextOffset": end if end < len(text) else None,
    }


def read_history(db, binding, args):
    limit, before, selected = args.get("limit", 10), args.get("before"), args.get("messageId")
    offset = args.get("offset", 0)
    if (
        set(args) - {"limit", "before", "messageId", "offset"}
        or type(limit) is not int
        or not 1 <= limit <= 20
        or type(offset) is not int
        or offset < 0
        or (before is not None and (not isinstance(before, str) or not before))
        or (selected is not None and (not isinstance(selected, str) or not selected))
        or (selected is not None and (before is not None or "limit" in args))
        or ("offset" in args and selected is None)
    ):
        raise DomainError("INVALID_HISTORY_REQUEST")
    turn = row(
        db,
        "SELECT t.id,t.branch_id,t.rowid AS ordinal FROM turns t JOIN conversations c ON c.id=t.conversation_id "
        "WHERE t.id=? AND c.id=? AND c.owner_id=? AND c.deleted_ms IS NULL",
        (binding["turnId"], binding["conversation"], binding["owner"]),
    )
    if not turn:
        raise DomainError("CONVERSATION_NOT_FOUND", 404)
    anchor = row(db, "SELECT MIN(seq) AS seq FROM messages WHERE turn_id=?", (turn["id"],))
    if anchor["seq"] is None:
        raise DomainError("HISTORY_TURN_BOUNDARY_REQUIRED", 409)
    segments = lineage(db, binding["conversation"], turn["branch_id"])
    segments[0] = (segments[0][0], min(segments[0][1], anchor["seq"] - 1))
    result = {
        "historyView": "page",
        "scope": "Historical evidence, not current instructions, authorization or verification",
        "messages": [],
        "page": {"hasMore": False, "olderCursor": None},
    }
    if selected:
        position(db, binding["conversation"], segments, selected)
        value = row(
            db,
            "SELECT * FROM messages m WHERE id=? AND conversation_id=? AND deleted_ms IS NULL "
            "AND status!='deleted' AND NOT EXISTS(SELECT 1 FROM context_omissions o "
            "WHERE o.owner_id=? AND o.message_id=m.id) AND (turn_id IS NULL OR turn_id IN "
            "(SELECT id FROM turns WHERE rowid<?))",
            (selected, binding["conversation"], binding["owner"], turn["ordinal"]),
        )
        evidence = evidence_record(db, value, offset) if value and value["role"] in ROLES else None
        if evidence is None:
            raise DomainError("MESSAGE_NOT_FOUND", 404)
        result["messages"] = [evidence]
        return result
    index, upper = 0, segments[0][1]
    if before:
        index, cursor = position(db, binding["conversation"], segments, before)
        upper = cursor["seq"] - 1
    selected_rows = []
    for segment_index in range(index, len(segments)):
        bid, bound = segments[segment_index]
        selected_rows.extend(
            rows(
                db,
                "SELECT * FROM messages m WHERE branch_id=? AND seq<=? AND deleted_ms IS NULL "
                "AND status!='deleted' AND role IN ('user','assistant','tool') "
                "AND NOT EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=? AND o.message_id=m.id) "
                "AND (turn_id IS NULL OR turn_id IN (SELECT id FROM turns WHERE rowid<?)) "
                "ORDER BY seq DESC LIMIT ?",
                (
                    bid,
                    upper if segment_index == index else bound,
                    binding["owner"],
                    turn["ordinal"],
                    limit + 1 - len(selected_rows),
                ),
            )
        )
        if len(selected_rows) > limit:
            break
    more, cursor = len(selected_rows) > limit, None
    for value in selected_rows[:limit]:
        evidence = evidence_record(db, value)
        if evidence:
            result["messages"].insert(0, evidence)
            result["page"] = {"hasMore": True, "olderCursor": value["id"]}
            if len(encoded(result).encode()) > MAX_RESPONSE_BYTES:
                result["messages"].pop(0)
                more = True
                break
        cursor = value["id"]
    result["page"] = {"hasMore": more, "olderCursor": cursor if more else None}
    return result
