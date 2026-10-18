"""Read bounded execution payloads only for activities visible in this conversation."""

import json
import re

from roami_agent.conversation.activity import conversation_activity
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.transcript_repository import history, owned

SENSITIVE = re.compile(
    r"^(api[-_]?key|authorization|password|passwd|secret|access[-_]?token|refresh[-_]?token|cookie|set-cookie|.*base64)$",
    re.IGNORECASE,
)


def preview(value):
    def redact(item, depth=0):
        if depth > 12:
            return "[nested content omitted]"
        if isinstance(item, dict):
            return {
                key: "[redacted]" if SENSITIVE.match(key) else redact(value, depth + 1)
                for key, value in item.items()
            }
        if isinstance(item, list):
            return [redact(value, depth + 1) for value in item]
        if isinstance(item, str):
            item = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[redacted]", item)
            item = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [redacted]", item)
            return re.sub(
                r"data:image/[^;\s]+;base64,[A-Za-z0-9+/=]+", "[image data omitted]", item
            )
        return item

    text = json.dumps(redact(value), ensure_ascii=False, indent=2)
    return {"text": text[:16000], "truncated": len(text) > 16000}


def activity_payload(db, owner, cid, aid, branch_id=None):
    conversation = owned(db, owner, cid)
    branch_id = branch_id or conversation["active_branch_id"]
    if not row(db, "SELECT id FROM branches WHERE id=? AND conversation_id=?", (branch_id, cid)):
        raise DomainError("BRANCH_NOT_FOUND", 404)
    activity = next(
        (
            item
            for item in conversation_activity(db, cid, history(db, branch_id))
            if item["id"] == aid
        ),
        None,
    )
    if not activity:
        raise DomainError("ACTIVITY_NOT_FOUND", 404)
    kind, _, ident = aid.partition(":")
    output = None
    if kind == "tool":
        call = row(
            db,
            "SELECT tc.*,m.content_json AS output_json,m.deleted_ms AS output_deleted,m.status AS output_status "
            "FROM tool_calls tc JOIN messages a ON a.id=tc.assistant_message_id "
            "LEFT JOIN messages m ON m.id=tc.result_message_id "
            "WHERE tc.id=? AND a.deleted_ms IS NULL AND a.status!='deleted'",
            (ident,),
        )
        if not call or call["output_deleted"] or call["output_status"] == "deleted":
            raise DomainError("ACTIVITY_DETAILS_UNAVAILABLE", 404)
        arguments = json.loads(call["arguments_json"])
        if call["output_json"]:
            content = json.loads(call["output_json"])
            try:
                output = json.loads(content["text"])
            except (ValueError, TypeError, KeyError):
                output = content
    elif kind == "task":
        task = row(db, "SELECT intent_json FROM tasks WHERE id=? AND owner_id=?", (ident, owner))
        if not task:
            raise DomainError("ACTIVITY_DETAILS_UNAVAILABLE", 404)
        arguments = json.loads(task["intent_json"])
        attempt = row(
            db,
            "SELECT result_json FROM task_attempts WHERE task_id=? ORDER BY attempt_no DESC LIMIT 1",
            (ident,),
        )
        if attempt and attempt["result_json"]:
            output = json.loads(attempt["result_json"])
    else:
        arguments = {}
        output = {"errorCode": activity.get("errorCode"), "state": activity["state"]}
    return {
        "id": aid,
        "state": activity["state"],
        "input": preview(arguments),
        "output": preview(output) if output is not None else None,
    }
