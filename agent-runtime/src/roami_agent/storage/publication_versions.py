"""Immutable original-team candidates; freezing content grants no channel access."""

import hashlib
import json
import re

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row
from roami_agent.storage.publication_author_scope import candidate_artifacts
from roami_agent.storage.publication_review_context import review_turn
from roami_agent.storage.swarm_delegations import current_delegation
from roami_agent.storage.swarm_repository import receipt


def current_goal(db, binding, scope):
    review_turn(db, binding)
    goal = current_delegation(db, binding["owner"], scope["swarmId"], scope["delegationId"])
    if (
        goal["projectId"] != scope["projectId"]
        or goal["mainConversationId"] != binding["conversation"]
    ):
        raise DomainError("PUBLICATION_PROJECT_SCOPE_CONFLICT", 403)
    if scope["memberId"] not in json.loads(goal["member_ids_json"]):
        raise DomainError("PUBLICATION_AUTHOR_NOT_SELECTED", 403)
    return goal


def create_item(db, binding, scope, business_key, channel):
    current_goal(db, binding, scope)
    if not isinstance(business_key, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,99}", business_key):
        raise DomainError("INVALID_PUBLICATION_BUSINESS_KEY")
    if channel not in {"x", "bilibili"}:
        raise DomainError("INVALID_PUBLICATION_CHANNEL")
    payload = {k: scope[k] for k in ["swarmId", "delegationId", "projectId", "memberId"]}
    payload.update(businessKey=business_key, channel=channel)

    def write():
        value = {"id": identity(), **payload, "createdMs": now_ms()}
        db.execute(
            "INSERT INTO swarm_publication_items(id,owner_id,project_id,swarm_id,delegation_id,member_id,business_key,channel,created_turn_id,created_ms) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                value["id"],
                binding["owner"],
                scope["projectId"],
                scope["swarmId"],
                scope["delegationId"],
                scope["memberId"],
                business_key,
                channel,
                binding["turnId"],
                value["createdMs"],
            ),
        )
        return {**value, "state": "draft", "publicationAuthorized": False}

    return receipt(
        db,
        binding["owner"],
        f"publication:item:{channel}:{business_key}",
        payload,
        write,
        swarm_id=scope["swarmId"],
    )


def freeze_version(db, binding, item_id, author, required, content, *, account_identity=None):
    item = row(
        db,
        "SELECT * FROM swarm_publication_items WHERE id=? AND owner_id=?",
        (item_id, binding["owner"]),
    )
    if not item:
        raise DomainError("PUBLICATION_ITEM_NOT_FOUND", 404)
    scope = {
        "swarmId": item["swarm_id"],
        "delegationId": item["delegation_id"],
        "projectId": item["project_id"],
        "memberId": item["member_id"],
    }
    current_goal(db, binding, scope)
    if any(author.get(k) != v for k, v in scope.items()):
        raise DomainError("PUBLICATION_PROJECT_SCOPE_CONFLICT", 403)
    if account_identity is not None and (
        not isinstance(account_identity, str)
        or not re.fullmatch(r"[1-9][0-9]{0,29}", account_identity)
    ):
        raise DomainError("INVALID_PUBLICATION_ACCOUNT_ID")
    if (
        not isinstance(content, dict)
        or not content
        or set(content) - {"body", "title", "tags", "images", "video", "audio", "subtitles"}
    ):
        raise DomainError("INVALID_PUBLICATION_CONTENT")
    artifacts = candidate_artifacts(db, binding, author, required)
    by_id = {a["id"]: a for a in artifacts}
    referenced = []
    for name, value in content.items():
        values = value if name == "images" else [value]
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(v, str) or v not in by_id for v in values)
        ):
            raise DomainError("PUBLICATION_ARTIFACTS_REQUIRED", 409)
        for aid in values:
            mime = by_id[aid]["mimeType"]
            expected = (
                "image/"
                if name == "images"
                else "video/"
                if name == "video"
                else "audio/"
                if name == "audio"
                else "text/"
            )
            if not mime.startswith(expected) and not (
                expected == "text/" and mime == "application/json"
            ):
                raise DomainError("PUBLICATION_ARTIFACT_TYPE_CONFLICT", 409)
        referenced.extend(values)
    if set(referenced) != set(by_id) or "body" not in content:
        raise DomainError("PUBLICATION_ARTIFACTS_REQUIRED", 409)
    manifest = {
        "schemaVersion": 1,
        "itemId": item_id,
        "channel": item["channel"],
        "accountIdentity": account_identity,
        "author": {k: author[k] for k in [*scope, "taskId", "revision", "runId"]},
        "content": content,
        "artifacts": sorted(artifacts, key=lambda value: value["id"]),
    }
    packed = encoded(manifest)
    digest = hashlib.sha256(packed.encode()).hexdigest()
    prior = row(
        db,
        "SELECT id,sequence FROM swarm_publication_versions WHERE item_id=? AND manifest_sha256=?",
        (item_id, digest),
    )
    if prior:
        return {
            "versionId": prior["id"],
            "sequence": prior["sequence"],
            "manifestSha256": digest,
            "state": "frozen",
            "publicationAuthorized": False,
        }
    version_id = identity()
    sequence = db.execute(
        "SELECT COALESCE(MAX(sequence),0)+1 FROM swarm_publication_versions WHERE item_id=?",
        (item_id,),
    ).fetchone()[0]
    content_identity = {
        name: [by_id[v]["sha256"] for v in value]
        if isinstance(value, list)
        else by_id[value]["sha256"]
        for name, value in content.items()
    }
    db.execute(
        "INSERT INTO swarm_publication_versions(id,item_id,sequence,author_task_id,author_revision,author_run_id,account_identity,manifest_json,manifest_sha256,content_sha256,created_turn_id,created_ms) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            version_id,
            item_id,
            sequence,
            author["taskId"],
            author["revision"],
            author["runId"],
            account_identity,
            packed,
            digest,
            hashlib.sha256(encoded(content_identity).encode()).hexdigest(),
            binding["turnId"],
            now_ms(),
        ),
    )
    return {
        "versionId": version_id,
        "sequence": sequence,
        "manifestSha256": digest,
        "state": "frozen",
        "publicationAuthorized": False,
    }
