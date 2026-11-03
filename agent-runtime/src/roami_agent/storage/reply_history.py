"""Delivered Main replies whose source request remains visible in brief history."""

import json

from roami_agent.storage.database import rows


def replied_message_ids(db, turn, message_ids):
    if not message_ids:
        return []
    return [
        result["id"]
        for result in rows(
            db,
            "WITH visible AS (SELECT value AS id FROM json_each(?)) "
            "SELECT DISTINCT m.id FROM events e JOIN messages m ON m.id=e.message_id "
            "JOIN turns t ON t.id=m.turn_id JOIN conversations c ON c.id=t.conversation_id "
            "WHERE e.kind='message.completed' AND e.turn_id=t.id "
            "AND e.conversation_id=? AND t.conversation_id=e.conversation_id AND c.owner_id=? "
            "AND t.state='completed' AND t.trigger_kind='user' "
            "AND json_extract(e.payload_json,'$.source')='main' "
            "AND json_extract(e.payload_json,'$.question') IS NULL "
            "AND m.role='assistant' AND m.status='completed' AND m.deleted_ms IS NULL "
            "AND json_extract(native_content(m.content_json),'$.question') IS NULL "
            "AND json_extract(native_content(m.content_json),'$.tool_calls') IS NULL "
            "AND m.id IN (SELECT id FROM visible) "
            "AND EXISTS(SELECT 1 FROM messages u WHERE u.turn_id=t.id AND u.role='user' "
            "AND u.deleted_ms IS NULL AND u.id IN (SELECT id FROM visible))",
            (json.dumps(message_ids), turn["conversation_id"], turn["owner_id"]),
        )
    ]
