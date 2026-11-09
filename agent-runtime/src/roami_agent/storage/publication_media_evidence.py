"""Current Main media evidence must originate in actual inspection and image inputs."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row, rows
from roami_agent.storage.publication_media_reads import media_tool_artifact
from roami_agent.storage.publication_media_sources import retained_media_source
from roami_agent.storage.publication_media_speech import completed_media_speech
from roami_agent.storage.publication_reviews import current_version


def reference(value):
    return {key: value[key] for key in ("id", "sha256", "sizeBytes", "mimeType")}


def media_snapshot(db, binding, version_id, required):
    _, manifest = current_version(db, binding, version_id)
    snapshots = []
    for source in required:
        selected = None
        for call in rows(
            db,
            "SELECT x.id,m.id AS result_id,native_content(m.content_json) AS body "
            "FROM tool_calls x JOIN messages m ON m.id=x.result_message_id JOIN messages current ON current.id=? "
            "WHERE x.turn_id=? AND x.tool_name='swarm_publication_media' AND x.state='succeeded' "
            "AND json_extract(x.arguments_json,'$.operation')='inspect' "
            "AND json_extract(x.arguments_json,'$.versionId')=? "
            "AND json_extract(x.arguments_json,'$.artifactId')=? "
            "AND m.conversation_id=? AND m.branch_id=current.branch_id AND m.turn_id=x.turn_id "
            "AND m.role='tool' AND m.deleted_ms IS NULL AND m.status='completed' AND m.seq<current.seq "
            "AND NOT EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=? AND o.message_id=m.id) "
            "ORDER BY x.rowid DESC",
            (
                binding["assistantMessageId"],
                binding["turnId"],
                version_id,
                source["id"],
                binding["conversation"],
                binding["owner"],
            ),
        ):
            try:
                value = json.loads(json.loads(call["body"])["text"])
                if (value["versionId"], value["sourceArtifactId"], value["sourceSha256"]) != (
                    version_id,
                    source["id"],
                    source["sha256"],
                ):
                    continue
                images = value["images"]
                if len(images) != (3 if source["mimeType"].startswith("video/") else 0):
                    continue
                refs = [value["report"], *images]
                if value["audio"]:
                    if value.get("transcriptionComplete") is not True:
                        continue
                    speech = completed_media_speech(
                        db,
                        binding["owner"],
                        manifest["author"]["projectId"],
                        {
                            "versionId": version_id,
                            "sourceArtifactId": source["id"],
                            "sourceSha256": source["sha256"],
                            "audioSha256": value["audio"]["sha256"],
                        },
                        value.get("speechIntentId"),
                    )
                    if (speech["response"], speech["transcript"]) != (
                        value["transcription"],
                        value["transcript"],
                    ):
                        continue
                    refs.extend([value["audio"], value["transcription"], value["transcript"]])
                for ref in refs:
                    artifact = media_tool_artifact(
                        db, binding["owner"], binding["conversation"], binding["turnId"], ref["id"]
                    )
                    if (
                        not artifact
                        or (artifact["sha256"], artifact["size_bytes"], artifact["mime_type"])
                        != (ref["sha256"], ref["sizeBytes"], ref["mimeType"])
                        or row(
                            db,
                            "SELECT 1 FROM memory_tombstones WHERE owner_id=? AND source_fingerprint=?",
                            (binding["owner"], artifact["sha256"]),
                        )
                    ):
                        raise DomainError("PUBLICATION_MEDIA_NOT_REVIEWED", 409)
                    metadata = json.loads(artifact["metadata_json"])
                    if metadata["mediaSource"] != {
                        "versionId": version_id,
                        "artifactId": source["id"],
                        "sha256": source["sha256"],
                    }:
                        raise DomainError("PUBLICATION_MEDIA_NOT_REVIEWED", 409)
                    retained_media_source(db, binding["owner"], metadata)
                selected = {
                    "sourceArtifactId": source["id"],
                    "sourceSha256": source["sha256"],
                    "inspectionToolCallId": call["id"],
                    "resultMessageId": call["result_id"],
                    "report": reference(value["report"]),
                    "images": [reference(ref) for ref in images],
                    "audio": reference(value["audio"]) if value["audio"] else None,
                    "transcript": reference(value["transcript"]) if value["audio"] else None,
                    "transcription": reference(value["transcription"]) if value["audio"] else None,
                    "speechIntentId": value.get("speechIntentId"),
                }
                break
            except (KeyError, TypeError, ValueError, DomainError):
                continue
        if selected is None:
            raise DomainError("PUBLICATION_MEDIA_NOT_REVIEWED", 409)
        snapshots.append(selected)
    return snapshots


def reviewed_media_images(db, binding, version_id, snapshots):
    manifest = row(
        db,
        "SELECT id,parts_json FROM prompt_manifests WHERE turn_id=? "
        "AND json_extract(parts_json,'$.role')='main' ORDER BY attempt_no DESC LIMIT 1",
        (binding["turnId"],),
    )
    evidence = json.loads(manifest["parts_json"]).get("imageEvidence", []) if manifest else []
    proof = []
    for snapshot in snapshots:
        for required in snapshot["images"]:
            found = None
            for image in evidence:
                if not isinstance(image, dict) or not isinstance(image.get("toolCallId"), str):
                    continue
                if (
                    image.get("source"),
                    image.get("versionId"),
                    image.get("artifactId"),
                    image.get("sha256"),
                    image.get("sourceArtifactId"),
                    image.get("sourceSha256"),
                ) != (
                    "publication_media",
                    version_id,
                    required["id"],
                    required["sha256"],
                    snapshot["sourceArtifactId"],
                    snapshot["sourceSha256"],
                ):
                    continue
                call = row(
                    db,
                    "SELECT x.id FROM tool_calls x JOIN messages m ON m.id=x.result_message_id "
                    "JOIN messages current ON current.id=? WHERE x.turn_id=? AND x.idempotency_key=? "
                    "AND x.tool_name='swarm_publication_media' AND x.state='succeeded' "
                    "AND json_extract(x.arguments_json,'$.operation')='image' "
                    "AND json_extract(x.arguments_json,'$.versionId')=? "
                    "AND json_extract(json_extract(m.content_json,'$.text'),'$.mediaImage.artifactId')=? "
                    "AND json_extract(json_extract(m.content_json,'$.text'),'$.mediaImage.sha256')=? "
                    "AND m.turn_id=x.turn_id AND m.conversation_id=? AND m.branch_id=current.branch_id "
                    "AND m.role='tool' AND m.status='completed' AND m.deleted_ms IS NULL AND m.seq<current.seq "
                    "AND NOT EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=? AND o.message_id=m.id)",
                    (
                        binding["assistantMessageId"],
                        binding["turnId"],
                        binding["turnId"] + ":" + image.get("toolCallId", ""),
                        version_id,
                        required["id"],
                        required["sha256"],
                        binding["conversation"],
                        binding["owner"],
                    ),
                )
                if call:
                    found = {
                        "artifactId": required["id"],
                        "sha256": required["sha256"],
                        "manifestId": manifest["id"],
                        "toolCallId": call["id"],
                    }
                    break
            if found is None:
                raise DomainError("PUBLICATION_MEDIA_IMAGE_NOT_REVIEWED", 409)
            proof.append(found)
    return proof
