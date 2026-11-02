"""Select Main file snapshots only through their current, persisted read receipts."""

import json

from roami_agent.protocol.image_limits import MAX_CONTEXT_IMAGES
from roami_agent.storage.database import row


async def main_file_images(database, turn, plan, prompt):
    if not turn.get("id") or turn.get("executionRunId"):
        return [], []
    sources, unavailable, seen = [], [], set()
    current = plan.get("currentTurnStart", 0) + 1
    for message in reversed(prompt[current:]):
        if message.get("role") != "tool" or not isinstance(message.get("content"), str):
            continue
        try:
            value = json.loads(message["content"])
        except (ValueError, TypeError):
            continue
        image = value.get("fileImage") if isinstance(value, dict) else None
        path = image.get("path") if isinstance(image, dict) else None
        if not isinstance(path, str) or not path or path in seen:
            continue
        seen.add(path)
        source = await database.call(
            lambda db, message=message, image=image, path=path: row(
                db,
                "SELECT a.* FROM tool_calls t JOIN messages m ON m.id=t.result_message_id "
                "JOIN turns u ON u.id=t.turn_id AND u.state='running' "
                "JOIN conversations c ON c.id=u.conversation_id "
                "JOIN artifacts a ON a.id=json_extract(json_extract(m.content_json,'$.text'),'$.fileImage.artifactId') "
                "WHERE t.turn_id=? AND t.idempotency_key=? AND t.tool_name='file_read' AND t.state='succeeded' "
                "AND m.turn_id=u.id AND m.branch_id=u.branch_id AND m.conversation_id=u.conversation_id "
                "AND a.message_id=t.assistant_message_id AND a.id=? AND a.owner_id=? "
                "AND c.owner_id=a.owner_id AND a.task_id IS NULL "
                "AND json_extract(a.metadata_json,'$.source')='workspace_image' "
                "AND json_extract(a.metadata_json,'$.readerRole')='main' "
                "AND json_extract(a.metadata_json,'$.runId') IS NULL "
                "AND json_extract(a.metadata_json,'$.turnId')=u.id "
                "AND json_extract(a.metadata_json,'$.toolCallId')=? "
                "AND json_extract(a.metadata_json,'$.sourcePath')=? "
                "AND NOT EXISTS(SELECT 1 FROM task_attempts r WHERE r.native_branch_id=u.branch_id) "
                "AND a.deleted_ms IS NULL AND NOT EXISTS(SELECT 1 FROM memory_tombstones f "
                "WHERE f.owner_id=a.owner_id AND f.source_fingerprint=a.sha256)",
                (
                    turn["id"],
                    turn["id"] + ":" + message.get("tool_call_id", ""),
                    image.get("artifactId"),
                    turn["owner_id"],
                    message.get("tool_call_id", ""),
                    path,
                ),
            )
        )
        if source:
            sources.append(source)
        else:
            unavailable.append(
                "Local image snapshot unavailable; do not claim to have inspected it: " + path
            )
        if len(sources) == MAX_CONTEXT_IMAGES:
            break
    return sources, unavailable
