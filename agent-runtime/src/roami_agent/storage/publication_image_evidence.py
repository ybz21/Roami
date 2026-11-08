"""Match frozen image hashes to this Main turn's genuine image-read inputs."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row, rows
from roami_agent.storage.publication_review_context import review_turn


def reviewed_images(db, binding, required):
    turn = review_turn(db, binding)
    matches = []
    for item in required:
        original = row(
            db,
            "SELECT id,sha256 FROM artifacts WHERE id=? AND owner_id=? AND sha256=? "
            "AND mime_type IN ('image/png','image/jpeg','image/webp') AND deleted_ms IS NULL "
            "AND purged_ms IS NULL AND NOT EXISTS(SELECT 1 FROM memory_tombstones f "
            "WHERE f.owner_id=artifacts.owner_id AND f.source_fingerprint=artifacts.sha256)",
            (item["id"], binding["owner"], item["sha256"]),
        )
        if not original:
            raise DomainError("PUBLICATION_IMAGE_UNAVAILABLE", 409)
        found = None
        for manifest in rows(
            db,
            "SELECT id,parts_json FROM prompt_manifests WHERE turn_id=? "
            "AND json_extract(parts_json,'$.role')='main' ORDER BY attempt_no DESC LIMIT 1",
            (turn["id"],),
        ):
            for image in json.loads(manifest["parts_json"]).get("imageEvidence", []):
                if (
                    image.get("sha256") != original["sha256"]
                    or image.get("source") != "workspace_file"
                ):
                    continue
                receipt = row(
                    db,
                    "SELECT a.id FROM tool_calls x JOIN messages m ON m.id=x.result_message_id "
                    "JOIN messages current ON current.id=? "
                    "JOIN artifacts a ON a.id=json_extract(json_extract(m.content_json,'$.text'),'$.fileImage.artifactId') "
                    "WHERE x.turn_id=? AND x.idempotency_key=? AND x.tool_name='file_read' AND x.state='succeeded' "
                    "AND m.turn_id=x.turn_id AND m.role='tool' AND m.deleted_ms IS NULL AND m.status='completed' "
                    "AND m.seq<current.seq AND x.assistant_message_id!=current.id "
                    "AND a.id=? AND a.owner_id=? AND a.task_id IS NULL AND a.message_id=x.assistant_message_id "
                    "AND a.sha256=? AND a.deleted_ms IS NULL AND a.purged_ms IS NULL "
                    "AND json_extract(a.metadata_json,'$.source')='workspace_image' "
                    "AND json_extract(a.metadata_json,'$.readerRole')='main' "
                    "AND json_extract(a.metadata_json,'$.turnId')=x.turn_id "
                    "AND json_extract(a.metadata_json,'$.toolCallId')=? "
                    "AND json_extract(a.metadata_json,'$.sourcePath')=?",
                    (
                        binding["assistantMessageId"],
                        turn["id"],
                        turn["id"] + ":" + image.get("toolCallId", ""),
                        image.get("artifactId"),
                        binding["owner"],
                        original["sha256"],
                        image.get("toolCallId"),
                        image.get("path"),
                    ),
                )
                if receipt:
                    found = {
                        "artifactId": original["id"],
                        "sha256": original["sha256"],
                        "imageReadArtifactId": receipt["id"],
                        "manifestId": manifest["id"],
                        "toolCallId": image["toolCallId"],
                    }
                    break
            if found:
                break
        if not found:
            raise DomainError("PUBLICATION_IMAGE_NOT_REVIEWED", 409)
        matches.append(found)
    return matches
