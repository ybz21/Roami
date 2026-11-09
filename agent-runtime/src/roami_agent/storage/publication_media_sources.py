"""Derived media stays unreadable when its original frozen sources are removed."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row


def retained_media_source(db, owner, metadata):
    source = metadata.get("mediaSource")
    if not isinstance(source, dict) or set(source) != {"versionId", "artifactId", "sha256"}:
        raise DomainError("PUBLICATION_MEDIA_SOURCE_UNAVAILABLE", 409)
    if any(not isinstance(value, str) or not value for value in source.values()):
        raise DomainError("PUBLICATION_MEDIA_SOURCE_UNAVAILABLE", 409)
    version = row(
        db,
        "SELECT v.manifest_json FROM swarm_publication_versions v "
        "JOIN swarm_publication_items p ON p.id=v.item_id WHERE v.id=? AND p.owner_id=?",
        (source["versionId"], owner),
    )
    if not version:
        raise DomainError("PUBLICATION_MEDIA_SOURCE_UNAVAILABLE", 409)
    manifest = json.loads(version["manifest_json"])
    selected = {manifest["content"].get(name) for name in ("video", "audio")}
    if source["artifactId"] not in selected or not any(
        item["id"] == source["artifactId"] and item["sha256"] == source["sha256"]
        for item in manifest["artifacts"]
    ):
        raise DomainError("PUBLICATION_MEDIA_SOURCE_UNAVAILABLE", 409)

    def retained(ident, digest):
        value = row(
            db,
            "SELECT metadata_json FROM artifacts WHERE id=? AND owner_id=? AND sha256=? "
            "AND deleted_ms IS NULL AND purged_ms IS NULL AND NOT EXISTS "
            "(SELECT 1 FROM memory_tombstones t WHERE t.owner_id=artifacts.owner_id "
            "AND t.source_fingerprint=artifacts.sha256)",
            (ident, owner, digest),
        )
        if not value or json.loads(value["metadata_json"]).get("kind") == "publication_media":
            raise DomainError("PUBLICATION_MEDIA_SOURCE_UNAVAILABLE", 409)

    retained(source["artifactId"], source["sha256"])
    parent = row(
        db,
        "SELECT manifest_artifact_id,manifest_sha256 FROM swarm_publication_source_files "
        "WHERE artifact_id=?",
        (source["artifactId"],),
    )
    if parent:
        retained(parent["manifest_artifact_id"], parent["manifest_sha256"])


def retained_review_media(db, owner, version_id, manifest, proof):
    selected = {
        manifest["content"][name] for name in ("video", "audio") if name in manifest["content"]
    }
    if not selected:
        return []
    try:
        snapshots = (proof.get("media") or {}).get("snapshot", [])
        if (
            len(snapshots) != len(selected)
            or {item["sourceArtifactId"] for item in snapshots} != selected
        ):
            raise DomainError("PUBLICATION_MEDIA_SOURCE_UNAVAILABLE", 409)
        by_id = {item["id"]: item for item in manifest["artifacts"]}
        references = {}
        for item in snapshots:
            source = {
                "versionId": version_id,
                "artifactId": item["sourceArtifactId"],
                "sha256": by_id[item["sourceArtifactId"]]["sha256"],
            }
            if item["sourceSha256"] != source["sha256"]:
                raise DomainError("PUBLICATION_MEDIA_SOURCE_UNAVAILABLE", 409)
            refs = [
                item["report"],
                *item["images"],
                *[
                    item.get(key)
                    for key in ("audio", "transcription", "transcript")
                    if item.get(key)
                ],
            ]
            for ref in refs:
                artifact = row(
                    db,
                    "SELECT metadata_json FROM artifacts WHERE id=? AND owner_id=? "
                    "AND sha256=? AND size_bytes=? AND mime_type=? AND deleted_ms IS NULL AND purged_ms IS NULL "
                    "AND NOT EXISTS(SELECT 1 FROM memory_tombstones t WHERE t.owner_id=artifacts.owner_id "
                    "AND t.source_fingerprint=artifacts.sha256)",
                    (ref["id"], owner, ref["sha256"], ref["sizeBytes"], ref["mimeType"]),
                )
                metadata = json.loads(artifact["metadata_json"]) if artifact else {}
                if (
                    metadata.get("kind") != "publication_media"
                    or metadata.get("mediaSource") != source
                ):
                    raise DomainError("PUBLICATION_MEDIA_SOURCE_UNAVAILABLE", 409)
                retained_media_source(db, owner, metadata)
                references[ref["id"]] = ref
        return list(references.values())
    except (AttributeError, KeyError, TypeError, ValueError):
        raise DomainError("PUBLICATION_MEDIA_SOURCE_UNAVAILABLE", 409) from None
