"""Current original-team authorship for a candidate; this grants no publication rights."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.publication_review_context import review_turn
from roami_agent.storage.swarm_delegations import current_delegation
from roami_agent.storage.task_deliverables import output_path, reported_paths


def candidate_author(db, binding, scope):
    review_turn(db, binding)
    goal = current_delegation(db, binding["owner"], scope["swarmId"], scope["delegationId"])
    if (
        goal["mainConversationId"] != binding["conversation"]
        or goal["projectId"] != scope["projectId"]
    ):
        raise DomainError("PUBLICATION_PROJECT_SCOPE_CONFLICT", 403)
    if scope["memberId"] not in json.loads(goal["member_ids_json"]):
        raise DomainError("PUBLICATION_AUTHOR_NOT_SELECTED", 403)
    author = row(
        db,
        "SELECT t.id,t.revision,t.state,a.id AS run_id,a.state AS run_state FROM swarm_members m "
        "JOIN swarm_member_work b ON b.member_id=m.id AND b.work_id=m.current_work_id "
        "JOIN swarm_work_items w ON w.id=b.work_id AND w.swarm_id=m.swarm_id "
        "JOIN tasks t ON t.id=w.task_id JOIN task_attempts a ON a.task_id=t.id AND a.task_revision=t.revision "
        "WHERE m.id=? AND m.swarm_id=? AND t.id=? AND t.owner_id=? "
        "AND t.origin_conversation_id=? AND t.revision=? AND a.id=? "
        "AND NOT EXISTS(SELECT 1 FROM task_attempts newer WHERE newer.task_id=a.task_id "
        "AND newer.task_revision=a.task_revision AND newer.attempt_no>a.attempt_no)",
        (
            scope["memberId"],
            scope["swarmId"],
            scope["taskId"],
            binding["owner"],
            binding["conversation"],
            scope["revision"],
            scope["runId"],
        ),
    )
    if not author or author["state"] != "succeeded" or author["run_state"] != "succeeded":
        raise DomainError("PUBLICATION_AUTHOR_NOT_CURRENT", 409)
    return {
        "projectId": goal["projectId"],
        "mainConversationId": goal["mainConversationId"],
        "swarmId": scope["swarmId"],
        "delegationId": goal["id"],
        "memberId": scope["memberId"],
        "taskId": author["id"],
        "revision": author["revision"],
        "runId": author["run_id"],
    }


def candidate_artifacts(db, binding, scope, required):
    candidate_author(db, binding, scope)
    if not required or len({item["id"] for item in required}) != len(required):
        raise DomainError("PUBLICATION_ARTIFACTS_REQUIRED", 409)
    attempt = row(db, "SELECT result_json FROM task_attempts WHERE id=?", (scope["runId"],))
    execution_result = json.loads(attempt["result_json"] or "{}")
    references = execution_result.get("artifactRefs", [])
    preparation = row(
        db,
        "SELECT payload_json FROM events WHERE event_key=? AND task_id=?",
        ("workspace:" + scope["runId"], scope["taskId"]),
    )
    workspace = json.loads(preparation["payload_json"]).get("workspace", {}) if preparation else {}
    root = workspace.get("directory")
    reported = set()
    if isinstance(root, str) and root:
        for field in ("summary", "output"):
            for path in reported_paths(execution_result.get(field, ""), root, include_inline=False):
                try:
                    reported.add(str(output_path(root, path)))
                except (TypeError, ValueError):
                    continue
    result = []
    for item in required:
        artifact = row(
            db,
            "SELECT * FROM artifacts WHERE id=? AND owner_id=? AND task_id=? AND sha256=? "
            "AND deleted_ms IS NULL AND purged_ms IS NULL "
            "AND json_extract(metadata_json,'$.kind')='deliverable' "
            "AND json_extract(metadata_json,'$.runId')=? "
            "AND COALESCE(json_extract(metadata_json,'$.provisional'),0)=0 "
            "AND NOT EXISTS(SELECT 1 FROM memory_tombstones f WHERE f.owner_id=artifacts.owner_id "
            "AND f.source_fingerprint=artifacts.sha256)",
            (item["id"], binding["owner"], scope["taskId"], item["sha256"], scope["runId"]),
        )
        native_reference = artifact and any(
            isinstance(ref, dict)
            and ref.get("id") == artifact["id"]
            and ref.get("sha256") == artifact["sha256"]
            and ref.get("sizeBytes") == artifact["size_bytes"]
            for ref in references
        )
        metadata = json.loads(artifact["metadata_json"]) if artifact else {}
        retained_cli_output = (
            execution_result.get("executor") == "roami-cli"
            and execution_result.get("state") == "succeeded"
            and execution_result.get("inputStopped") is True
            and execution_result.get("outcomeKnown") is True
            and isinstance(metadata.get("sourceFile"), str)
            and metadata["sourceFile"] in reported
        )
        derived = (
            row(
                db,
                "SELECT p.id,p.sha256 FROM swarm_publication_source_files s JOIN artifacts p ON p.id=s.manifest_artifact_id "
                "WHERE s.artifact_id=? AND s.source_sha256=? AND s.source_size=? AND s.manifest_sha256=p.sha256",
                (artifact["id"], artifact["sha256"], artifact["size_bytes"]),
            )
            if artifact
            else None
        )
        if derived:
            # A derived file cannot become its own provenance or another derived manifest.
            parent = row(
                db,
                "SELECT 1 FROM swarm_publication_source_files WHERE artifact_id=?",
                (derived["id"],),
            )
            if parent:
                raise DomainError("PUBLICATION_ARTIFACT_NOT_CURRENT", 409)
            candidate_artifacts(db, binding, scope, [derived])
        if not artifact or not (native_reference or retained_cli_output or derived):
            raise DomainError("PUBLICATION_ARTIFACT_NOT_CURRENT", 409)
        result.append(
            {
                "id": artifact["id"],
                "sha256": artifact["sha256"],
                "sizeBytes": artifact["size_bytes"],
                "mimeType": artifact["mime_type"],
            }
        )
    return result
