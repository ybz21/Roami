"""Index approved assets after the producer moves on; physical bytes need separate checks."""

import hashlib
import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row
from roami_agent.storage.swarm_delegations import current_delegation, visible_source


def approved_assets(db, owner, scope, version_id, review_id, channel, account):
    goal = current_delegation(db, owner, scope["swarmId"], scope["delegationId"])
    if goal["projectId"] != scope["projectId"] or scope["memberId"] not in json.loads(
        goal["member_ids_json"]
    ):
        raise DomainError("PUBLICATION_PROJECT_SCOPE_CONFLICT", 403)
    version = row(
        db,
        "SELECT v.*,p.swarm_id,p.project_id,p.member_id,p.delegation_id,p.channel,p.business_key FROM swarm_publication_versions v JOIN swarm_publication_items p ON p.id=v.item_id WHERE v.id=? AND p.owner_id=?",
        (version_id, owner),
    )
    if not version or any(
        version[key] != scope[name]
        for key, name in [
            ("swarm_id", "swarmId"),
            ("project_id", "projectId"),
            ("member_id", "memberId"),
            ("delegation_id", "delegationId"),
        ]
    ):
        raise DomainError("PUBLICATION_VERSION_SCOPE_CONFLICT", 403)
    if version["channel"] != channel or not account or version["account_identity"] != account:
        raise DomainError("PUBLICATION_ACCOUNT_SCOPE_CONFLICT", 403)
    if row(
        db,
        "SELECT 1 FROM swarm_publication_versions WHERE item_id=? AND sequence>?",
        (version["item_id"], version["sequence"]),
    ):
        raise DomainError("PUBLICATION_VERSION_SUPERSEDED", 409)
    review = row(
        db,
        "SELECT * FROM swarm_publication_reviews WHERE version_id=? ORDER BY created_ms DESC,rowid DESC LIMIT 1",
        (version_id,),
    )
    if not review or review["id"] != review_id or review["decision"] != "approved":
        raise DomainError("PUBLICATION_APPROVAL_REQUIRED", 409)
    message = row(
        db,
        "SELECT m.* FROM messages m JOIN turns t ON t.id=m.turn_id WHERE m.id=? AND t.id=? AND m.conversation_id=? AND m.role='assistant' AND m.deleted_ms IS NULL AND m.status!='deleted'",
        (review["assistant_message_id"], review["turn_id"], goal["mainConversationId"]),
    )
    branch = db.execute(
        "SELECT active_branch_id FROM conversations WHERE id=?", (goal["mainConversationId"],)
    ).fetchone()[0]
    if (
        not message
        or not visible_source(db, branch, message)
        or row(
            db,
            "SELECT 1 FROM context_omissions o JOIN messages m ON m.id=o.message_id WHERE o.owner_id=? AND m.turn_id=? LIMIT 1",
            (owner, review["turn_id"]),
        )
    ):
        raise DomainError("PUBLICATION_REVIEW_SOURCE_UNAVAILABLE", 409)
    manifest = json.loads(version["manifest_json"])
    if (
        hashlib.sha256(encoded(manifest).encode()).hexdigest() != version["manifest_sha256"]
        or json.loads(review["proof_json"]).get("manifestSha256") != version["manifest_sha256"]
    ):
        raise DomainError("PUBLICATION_MANIFEST_INTEGRITY_FAILED", 409)
    for item in manifest["artifacts"]:
        available = row(
            db,
            "SELECT id FROM artifacts a WHERE id=? AND owner_id=? AND sha256=? AND size_bytes=? AND mime_type=? AND deleted_ms IS NULL AND purged_ms IS NULL AND NOT EXISTS(SELECT 1 FROM memory_tombstones t WHERE t.owner_id=a.owner_id AND t.source_fingerprint=a.sha256)",
            (item["id"], owner, item["sha256"], item["sizeBytes"], item["mimeType"]),
        )
        if not available:
            raise DomainError("PUBLICATION_ARTIFACT_UNAVAILABLE", 409)
    return {
        "itemId": version["item_id"],
        "businessKey": version["business_key"],
        "versionId": version_id,
        "reviewId": review_id,
        "manifestSha256": version["manifest_sha256"],
        "manifest": manifest,
        "publicationAuthorized": False,
    }
