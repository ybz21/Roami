"""Separate agent-written continuation plans from their actual user request."""

import json

from roami_agent.storage.database import row


def task_user_request(db, message):
    content = json.loads(message["content_json"])
    if not content.get("taskSteer"):
        return message
    source_id = content.get("sourceUserMessageId")
    if not source_id and content.get("operationId"):
        receipt = row(
            db,
            "SELECT u.id FROM tool_calls x JOIN messages r ON r.id=x.result_message_id "
            "JOIN messages u ON u.turn_id=x.turn_id AND u.role='user' "
            "WHERE x.tool_name='task_steer' AND x.state='succeeded' "
            "AND u.conversation_id=? AND CASE WHEN json_valid(json_extract(native_content(r.content_json),'$.text')) "
            "THEN json_extract(json_extract(native_content(r.content_json),'$.text'),'$.operationId') END=? ORDER BY u.seq LIMIT 1",
            (message["conversation_id"], content["operationId"]),
        )
        source_id = receipt["id"] if receipt else None
    if not source_id:
        return message
    return row(
        db,
        "SELECT m.* FROM messages m JOIN conversations c ON c.id=m.conversation_id "
        "WHERE m.id=? AND m.conversation_id=? AND m.deleted_ms IS NULL AND NOT EXISTS "
        "(SELECT 1 FROM context_omissions o WHERE o.owner_id=c.owner_id AND o.message_id=m.id)",
        (source_id, message["conversation_id"]),
    )
