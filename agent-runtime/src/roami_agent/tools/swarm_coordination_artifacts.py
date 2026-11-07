"""Admit only a recorded host tool-response artifact from this exact Main batch."""

import json

from roami_agent.storage.database import row, rows
from roami_agent.tools.swarm_coordination_catalog import COORDINATION_OPERATIONS


def current_tool_artifact(db, value, artifact_id):
    artifact = row(
        db,
        "SELECT a.* FROM artifacts a JOIN messages m ON m.id=a.message_id "
        "WHERE a.id=? AND a.owner_id=? AND a.task_id IS NULL AND a.deleted_ms IS NULL "
        "AND m.turn_id=? AND m.conversation_id=? AND m.role='assistant' AND m.deleted_ms IS NULL "
        "AND NOT EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=a.owner_id AND o.message_id=m.id)",
        (artifact_id, value["owner_id"], value["turn_id"], value["conversation_id"]),
    )
    if artifact is None:
        return False
    metadata = json.loads(artifact["metadata_json"])
    if (
        metadata.get("source") != "tool_result"
        or metadata.get("toolName") not in COORDINATION_OPERATIONS
    ):
        return False
    for result in rows(
        db,
        "SELECT native_content(m.content_json) AS body FROM tool_calls x JOIN messages m ON m.id=x.result_message_id "
        "WHERE x.turn_id=? AND x.assistant_message_id=? AND x.tool_name=? AND x.state='succeeded' "
        "AND m.role='tool' AND m.deleted_ms IS NULL AND m.status='completed' "
        "AND NOT EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=? AND o.message_id=m.id)",
        (value["turn_id"], artifact["message_id"], metadata["toolName"], value["owner_id"]),
    ):
        try:
            body = json.loads(json.loads(result["body"]).get("text", "null"))
        except (ValueError, TypeError):
            continue
        if not isinstance(body, dict) or body.get("outputExternalized") is not True:
            continue
        for reference in body.get("artifactRefs", []):
            if (
                isinstance(reference, dict)
                and reference.get("id") == artifact_id
                and reference.get("sha256") == artifact["sha256"]
                and reference.get("sizeBytes") == artifact["size_bytes"]
            ):
                return True
    return False
