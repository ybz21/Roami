"""Allow derived media reads only through this Main turn's genuine inspect result."""

import json

from roami_agent.storage.database import row, rows


def media_tool_artifact(db, owner, conversation, turn_id, artifact_id):
    artifact = row(
        db,
        "SELECT * FROM artifacts WHERE id=? AND owner_id=? AND deleted_ms IS NULL "
        "AND purged_ms IS NULL AND json_extract(metadata_json,'$.kind')='publication_media'",
        (artifact_id, owner),
    )
    if not artifact:
        return None
    source = json.loads(artifact["metadata_json"])["mediaSource"]
    for item in rows(
        db,
        "SELECT native_content(m.content_json) AS body FROM tool_calls x JOIN messages m ON m.id=x.result_message_id "
        "WHERE x.turn_id=? AND x.tool_name='swarm_publication_media' AND x.state='succeeded' "
        "AND json_extract(x.arguments_json,'$.operation')='inspect' "
        "AND json_extract(x.arguments_json,'$.versionId')=? AND m.conversation_id=? "
        "AND m.turn_id=x.turn_id AND m.role='tool' AND m.status='completed' AND m.deleted_ms IS NULL "
        "AND NOT EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=? AND o.message_id=m.id)",
        (turn_id, source["versionId"], conversation, owner),
    ):
        try:
            result = json.loads(json.loads(item["body"])["text"])
        except (KeyError, TypeError, ValueError):
            continue
        if not isinstance(result, dict) or (
            result.get("sourceArtifactId"),
            result.get("sourceSha256"),
        ) != (source["artifactId"], source["sha256"]):
            continue
        references = [
            *result.get("images", []),
            *[result.get(key) for key in ("audio", "report", "transcription", "transcript")],
        ]
        if any(
            isinstance(ref, dict)
            and ref.get("id") == artifact_id
            and ref.get("sha256") == artifact["sha256"]
            and ref.get("sizeBytes") == artifact["size_bytes"]
            for ref in references
        ):
            return artifact
    return None
