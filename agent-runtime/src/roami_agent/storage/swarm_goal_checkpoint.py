"""Read real next-step evidence from an original Main's current goal scope."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row, rows
from roami_agent.storage.swarm_coordination_results import (
    _source_available as task_source_available,
)
from roami_agent.storage.swarm_coordination_tasks import request_context


def checkpoint_context(db, binding):
    value = request_context(db, binding["owner"], binding.get("turnId"), binding.get("leaseEpoch"))
    if value is None:
        return None
    if (
        binding.get("role") != "main"
        or binding.get("taskId")
        or binding.get("conversation") != value["conversation_id"]
    ):
        raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
    return value


def active_next_steps(db, binding):
    value = checkpoint_context(db, binding)
    if value is None:
        return None
    goal = value["delegation"]
    tasks = rows(
        db,
        "SELECT t.* FROM swarm_members m JOIN swarm_work_items w ON w.id=m.current_work_id "
        "JOIN tasks t ON t.id=w.task_id WHERE m.swarm_id=? AND t.owner_id=? "
        "AND t.origin_conversation_id=? AND m.id IN (SELECT value FROM json_each(?)) "
        "ORDER BY t.id",
        (value["swarm_id"], binding["owner"], value["conversation_id"], goal["member_ids_json"]),
    )
    proofs = []
    for task in tasks:
        if not task_source_available(db, task):
            continue
        run = row(
            db,
            "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=? "
            "ORDER BY attempt_no DESC LIMIT 1",
            (task["id"], task["revision"]),
        )
        if not run:
            continue
        identity = {"taskId": task["id"], "revision": task["revision"], "runId": run["id"]}
        if (
            task["state"] in {"preparing", "queued"}
            and run["state"] == "accepted"
            and run["finished_ms"] is None
        ):
            scheduled = row(
                db,
                "SELECT id FROM jobs WHERE kind='task.run' AND aggregate_id=? "
                "AND state IN ('queued','running') AND json_extract(payload_json,'$.runId')=? "
                "ORDER BY rowid LIMIT 1",
                (task["id"], run["id"]),
            )
            if scheduled:
                proofs.append(
                    {"kind": "pending_original_execution", "jobId": scheduled["id"], **identity}
                )
        pending = rows(
            db,
            "SELECT id,payload_json FROM jobs WHERE kind='task.steer' AND aggregate_id=? "
            "AND state IN ('queued','running') ORDER BY rowid",
            (task["id"],),
        )
        for job in pending:
            payload = json.loads(job["payload_json"])
            authorization = payload.get("coordinationAuthorization")
            if payload.get("expectedRevision") != task["revision"]:
                continue
            if authorization is not None and (
                not isinstance(authorization, dict)
                or authorization.get("delegationId") != goal["id"]
                or authorization.get("swarmId") != value["swarm_id"]
                or authorization.get("taskId") != task["id"]
                or authorization.get("sourceTaskRevision") != task["revision"]
                or authorization.get("sourceRunId") != run["id"]
            ):
                continue
            proofs.append({"kind": "pending_continuation", "jobId": job["id"], **identity})
        if (
            task["state"] in {"preparing", "running"}
            and run["state"] in {"starting", "running"}
            and run["finished_ms"] is None
        ):
            proofs.append({"kind": "running_original_task", **identity})
    return {
        "swarmId": value["swarm_id"],
        "batchId": value["id"],
        "delegationId": goal["id"],
        "delegationRevision": goal["revision"],
        "steps": proofs,
    }


def action_batch(value):
    return bool(value.get("results")) or any(
        item.get("kind") == "handoff" for item in value["inputs"]
    )


def stored_checkpoint(db, binding, value, prefix):
    found = row(
        db,
        "SELECT receipt_json FROM swarm_commands WHERE owner_id=? AND scope_project_id=? "
        "AND command_key=?",
        (
            binding["owner"],
            value["delegation"]["projectId"],
            prefix + value["id"] + ":" + str(value["lease_epoch"]),
        ),
    )
    return json.loads(found["receipt_json"]) if found else None


def failed_step(db, binding, call_id):
    found = row(
        db,
        "SELECT x.id,x.tool_name,native_content(m.content_json) AS body FROM tool_calls x "
        "JOIN messages m ON m.id=x.result_message_id WHERE x.turn_id=? "
        "AND (x.id=? OR x.idempotency_key=?) AND x.state IN ('failed','unknown') "
        "AND m.turn_id=x.turn_id AND m.conversation_id=? AND m.role='tool' "
        "AND m.status='completed' AND m.deleted_ms IS NULL AND NOT EXISTS("
        "SELECT 1 FROM context_omissions o WHERE o.owner_id=? AND o.message_id=m.id)",
        (
            binding["turnId"],
            call_id,
            binding["turnId"] + ":" + call_id,
            binding["conversation"],
            binding["owner"],
        ),
    )
    if found is None or found["tool_name"] in {"reply", "ask_user", "swarm_goal_checkpoint"}:
        raise DomainError("SWARM_GOAL_BLOCKER_EVIDENCE_REQUIRED", 409)
    try:
        error = json.loads(json.loads(found["body"])["text"])["error"]
    except (ValueError, KeyError, TypeError):
        raise DomainError("SWARM_GOAL_BLOCKER_EVIDENCE_REQUIRED", 409) from None
    allowed = isinstance(error, str) and (
        error.endswith(("_UNAVAILABLE", "_NOT_CONFIGURED", "_LOGIN_REQUIRED", "_AUTH_REQUIRED"))
        or error
        in {
            "TOOL_DISABLED",
            "TOOL_OUTCOME_UNKNOWN",
            "RESOURCE_PAUSED",
            "RESOURCE_TAKEN_OVER",
            "CONTEXT_SOURCE_FORGOTTEN",
        }
    )
    if not allowed or error in {"SWARM_COORDINATION_OPERATION_UNAVAILABLE", "TOOL_UNAVAILABLE"}:
        raise DomainError("SWARM_GOAL_BLOCKER_EVIDENCE_REQUIRED", 409)
    return {"toolCallId": found["id"], "tool": found["tool_name"], "error": error}


def record_blocker(db, binding, args):
    from roami_agent.storage.swarm_repository import receipt

    value = checkpoint_context(db, binding)
    if value is None or args["swarmId"] != value["swarm_id"]:
        raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
    reason = args["reason"].strip()
    if not reason:
        raise DomainError("SWARM_GOAL_BLOCKER_EVIDENCE_REQUIRED", 409)
    failure = failed_step(db, binding, args["failedToolCallId"])
    payload = {
        "batchId": value["id"],
        "delegationId": value["delegation"]["id"],
        "delegationRevision": value["delegation"]["revision"],
        "sourceSha256": value["delegation"]["source_sha256"],
        "leaseEpoch": value["lease_epoch"],
        "reason": reason,
        "failure": failure,
    }
    return receipt(
        db,
        binding["owner"],
        "goal-blocker:" + value["id"] + ":" + str(value["lease_epoch"]),
        payload,
        lambda: {"kind": "goal_blocker", "goalComplete": False, **payload},
        swarm_id=value["swarm_id"],
    )


def current_blocker(db, binding, value):
    proposal = stored_checkpoint(db, binding, value, "goal-blocker:")
    if proposal is None:
        return None
    if (
        proposal.get("delegationId") != value["delegation"]["id"]
        or proposal.get("delegationRevision") != value["delegation"]["revision"]
        or proposal.get("sourceSha256") != value["delegation"]["source_sha256"]
        or failed_step(db, binding, proposal["failure"]["toolCallId"]) != proposal["failure"]
    ):
        raise DomainError("SWARM_GOAL_CHECKPOINT_CHANGED", 409)
    return proposal


def accepted_checkpoint(db, binding, value):
    proof = stored_checkpoint(db, binding, value, "goal-checkpoint:")
    if proof is None:
        return None
    if (
        proof.get("kind") != "goal_checkpoint"
        or proof.get("delegationId") != value["delegation"]["id"]
        or proof.get("delegationRevision") != value["delegation"]["revision"]
        or proof.get("sourceSha256") != value["delegation"]["source_sha256"]
        or proof.get("turnId") != binding["turnId"]
        or proof.get("leaseEpoch") != binding["leaseEpoch"]
    ):
        raise DomainError("SWARM_GOAL_CHECKPOINT_CHANGED", 409)
    return proof


def save_checkpoint(db, binding, decision):
    from roami_agent.storage.swarm_repository import receipt

    value = checkpoint_context(db, binding)
    if value is None:
        raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
    payload = {
        "batchId": value["id"],
        "delegationId": value["delegation"]["id"],
        "delegationRevision": value["delegation"]["revision"],
        "sourceSha256": value["delegation"]["source_sha256"],
        "turnId": binding["turnId"],
        "leaseEpoch": binding["leaseEpoch"],
        "decision": decision,
    }
    return receipt(
        db,
        binding["owner"],
        "goal-checkpoint:" + value["id"] + ":" + str(value["lease_epoch"]),
        payload,
        lambda: {"kind": "goal_checkpoint", **payload},
        swarm_id=value["swarm_id"],
    )


def validate_final_checkpoint(db, turn):
    binding = {
        "owner": turn["owner_id"],
        "conversation": turn["conversation_id"],
        "turnId": turn["id"],
        "leaseEpoch": turn.get("lease_epoch"),
        "role": "main",
    }
    value = checkpoint_context(db, binding)
    if value is not None:
        # Later completion does not erase the accepted handoff; its callback remains independent.
        accepted_checkpoint(db, binding, value)
