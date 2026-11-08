"""Persist independent decisions against an exact immutable candidate version."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row
from roami_agent.storage.publication_author_scope import candidate_artifacts
from roami_agent.storage.publication_versions import current_goal


def current_version(db, binding, version_id):
    value = row(
        db,
        "SELECT v.*,p.owner_id FROM swarm_publication_versions v JOIN swarm_publication_items p ON p.id=v.item_id WHERE v.id=? AND p.owner_id=?",
        (version_id, binding["owner"]),
    )
    if not value:
        raise DomainError("PUBLICATION_VERSION_NOT_FOUND", 404)
    if row(
        db,
        "SELECT 1 FROM swarm_publication_versions WHERE item_id=? AND sequence>?",
        (value["item_id"], value["sequence"]),
    ):
        raise DomainError("PUBLICATION_VERSION_SUPERSEDED", 409)
    manifest = json.loads(value["manifest_json"])
    author = manifest["author"]
    current_goal(db, binding, author)
    candidate_artifacts(db, binding, author, manifest["artifacts"])
    return value, manifest


def save_review(db, binding, version_id, decision, feedback, proof):
    version, _ = current_version(db, binding, version_id)
    if (
        decision not in {"approved", "rejected"}
        or not isinstance(feedback, str)
        or not 1 <= len(feedback.strip()) <= 8000
    ):
        raise DomainError("INVALID_PUBLICATION_REVIEW")
    if decision == "approved" and proof.get("images"):
        from roami_agent.storage.publication_image_evidence import reviewed_images

        manifest = json.loads(version["manifest_json"])
        by_id = {item["id"]: item for item in manifest["artifacts"]}
        current_images = reviewed_images(
            db, binding, [by_id[ident] for ident in manifest["content"]["images"]]
        )
        if current_images != proof["images"]:
            raise DomainError("PUBLICATION_IMAGE_REVIEW_CHANGED", 409)
    payload = {**proof, "manifestSha256": version["manifest_sha256"]}
    previous = row(
        db,
        "SELECT * FROM swarm_publication_reviews WHERE version_id=? AND turn_id=?",
        (version_id, binding["turnId"]),
    )
    if previous:
        if (
            previous["decision"] != decision
            or previous["feedback"] != feedback.strip()
            or previous["proof_json"] != encoded(payload)
        ):
            raise DomainError("PUBLICATION_REVIEW_CONFLICT", 409)
        review_id = previous["id"]
    else:
        review_id = identity()
        db.execute(
            "INSERT INTO swarm_publication_reviews(id,version_id,turn_id,assistant_message_id,lease_epoch,decision,proof_json,feedback,created_ms) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                review_id,
                version_id,
                binding["turnId"],
                binding["assistantMessageId"],
                binding["leaseEpoch"],
                decision,
                encoded(payload),
                feedback.strip(),
                now_ms(),
            ),
        )
    return {
        "reviewId": review_id,
        "versionId": version_id,
        "manifestSha256": version["manifest_sha256"],
        "decision": decision,
        "publicationAuthorized": False,
    }
