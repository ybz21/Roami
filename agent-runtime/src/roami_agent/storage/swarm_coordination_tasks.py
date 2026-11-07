"""Keep a bounded member assignment tied to its original ongoing user goal."""

import json
from pathlib import Path

from roami_agent.dispatch.task_sessions import assert_session_open
from roami_agent.protocol.errors import DomainError, ToolPreflightError
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row
from roami_agent.storage.swarm_coordination import admitted_batch
from roami_agent.storage.swarm_coordination_admission import for_turn
from roami_agent.storage.swarm_delegations import current_delegation


def request_context(db, owner, turn_id, lease_epoch):
    if not turn_id:
        return None
    turn = row(
        db,
        "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=? AND c.owner_id=?",
        (turn_id, owner),
    )
    if not turn:
        return None
    value = for_turn(db, {**turn, "lease_epoch": lease_epoch})
    return admitted_batch(db, owner, turn_id, lease_epoch=lease_epoch) if value else None


def workspace(db, task, project_id, directory):
    target = json.loads(task["target_json"] or "{}")
    intent = json.loads(task["intent_json"]).get("target", {})
    associated = (
        target.get("projectId")
        or (target.get("workspace") or {}).get("projectId")
        or intent.get("projectId")
    )
    if associated is not None and associated != project_id:
        raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
    actual = (
        target.get("workdir")
        or (target.get("workspace") or {}).get("directory")
        or intent.get("directory")
    )
    if actual is None and associated == project_id and intent.get("kind") == "project":
        actual = directory
    if not isinstance(actual, str) or not Path(actual).is_absolute():
        raise DomainError("SWARM_COORDINATION_WORKSPACE_REQUIRED", 409)
    root, actual = Path(directory).resolve(), Path(actual).resolve()
    if actual != root and root not in actual.parents:
        raise DomainError("SWARM_COORDINATION_WORKSPACE_CHANGED", 409)
    return {"projectDirectory": str(root), "taskDirectory": str(actual)}


def create_authority(db, task, context, project_workspace):
    delegation = context["delegation"]
    if not project_workspace or project_workspace.get("projectId") != delegation["projectId"]:
        raise DomainError("SWARM_COORDINATION_WORKSPACE_REQUIRED", 409)
    if (
        not isinstance(project_workspace.get("directory"), str)
        or not Path(project_workspace["directory"]).is_absolute()
    ):
        raise DomainError("SWARM_COORDINATION_WORKSPACE_REQUIRED", 409)
    member = row(
        db,
        "SELECT m.id FROM swarm_members m JOIN swarm_work_items w ON w.id=m.current_work_id WHERE m.swarm_id=? AND w.task_id=?",
        (context["swarm_id"], task["id"]),
    )
    if not member or member["id"] not in json.loads(delegation["member_ids_json"]):
        raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
    run = row(
        db,
        "SELECT id FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
        (task["id"], task["revision"]),
    )
    if not run or task["origin_conversation_id"] != context["conversation_id"]:
        raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
    locations = workspace(db, task, delegation["projectId"], project_workspace["directory"])
    return {
        "batchId": context["id"],
        "swarmId": context["swarm_id"],
        "delegationId": delegation["id"],
        "memberId": member["id"],
        "taskId": task["id"],
        "mainTurnId": context["turn_id"],
        "mainBranchId": context["branch_id"],
        "sourceMessageId": delegation["source_message_id"],
        "sourceSha256": delegation["source_sha256"],
        "goalQuote": delegation["source_quote"],
        "projectId": delegation["projectId"],
        **locations,
        "sourceTaskRevision": task["revision"],
        "sourceRunId": run["id"],
    }


def current_authority(db, task, authorization):
    value = current_delegation(
        db, task["owner_id"], authorization["swarmId"], authorization["delegationId"]
    )
    batch = row(
        db,
        "SELECT b.*,t.branch_id,c.active_branch_id FROM swarm_coordination_batches b JOIN turns t ON t.id=b.turn_id JOIN conversations c ON c.id=t.conversation_id WHERE b.id=?",
        (authorization["batchId"],),
    )
    member = row(
        db,
        "SELECT m.id FROM swarm_members m JOIN swarm_work_items w ON w.id=m.current_work_id WHERE m.id=? AND m.swarm_id=? AND w.task_id=?",
        (authorization["memberId"], authorization["swarmId"], task["id"]),
    )
    if (
        not batch
        or not member
        or member["id"] not in json.loads(value["member_ids_json"])
        or batch["delegation_id"] != value["id"]
        or batch["turn_id"] != authorization["mainTurnId"]
        or batch["branch_id"] != authorization["mainBranchId"]
        or batch["active_branch_id"] != batch["branch_id"]
        or task["id"] != authorization["taskId"]
        or task["origin_conversation_id"] != value["mainConversationId"]
        or value["source_message_id"] != authorization["sourceMessageId"]
        or value["source_sha256"] != authorization["sourceSha256"]
        or value["source_quote"] != authorization["goalQuote"]
        or value["projectId"] != authorization["projectId"]
    ):
        raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
    assert_context_admitted(db, {"id": batch["turn_id"], "owner_id": task["owner_id"]})
    assert_session_open(db, task["id"])
    source_run = row(
        db,
        "SELECT id FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
        (task["id"], authorization["sourceTaskRevision"]),
    )
    if not source_run or source_run["id"] != authorization["sourceRunId"]:
        raise DomainError("TASK_RESULT_SUPERSEDED", 409)
    locations = workspace(db, task, value["projectId"], authorization["projectDirectory"])
    if locations["taskDirectory"] != authorization["taskDirectory"]:
        raise DomainError("SWARM_COORDINATION_WORKSPACE_CHANGED", 409)
    return value


def assert_dispatch_authorized(db, task, run):
    authorization = json.loads(task["intent_json"]).get("coordinationAuthorization")
    if authorization is None:
        return
    try:
        actual = row(
            db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (task["id"], task["owner_id"])
        )
        if (
            not actual
            or actual["revision"] != run["task_revision"]
            or actual["state"] not in {"queued", "preparing", "running"}
        ):
            raise DomainError("TASK_CANCELLING", 409)
        if json.loads(actual["intent_json"]).get("coordinationAuthorization") != authorization:
            raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
        task = actual
        current_authority(db, task, authorization)
        job = row(
            db,
            "SELECT payload_json FROM jobs WHERE id=? AND kind='task.steer' AND aggregate_id=? AND state='done'",
            (authorization["operationId"], task["id"]),
        )
        payload = json.loads(job["payload_json"]) if job else {}
        latest = row(
            db,
            "SELECT id FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
            (task["id"], task["revision"]),
        )
        if (
            payload.get("coordinationAuthorization") != authorization
            or payload.get("appliedRevision") != task["revision"]
            or payload.get("runId") != run["id"]
            or not latest
            or latest["id"] != run["id"]
            or run["task_revision"] != task["revision"]
        ):
            raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
    except DomainError as exc:
        raise ToolPreflightError(exc.code, exc.status) from exc


async def prepared_authority(database, task, run, project_workspace):
    authorization = json.loads(task["intent_json"]).get("coordinationAuthorization")
    if authorization is None:
        return
    await database.call(lambda db: assert_dispatch_authorized(db, task, run))
    if project_workspace is None:
        raise ToolPreflightError("SWARM_COORDINATION_WORKSPACE_REQUIRED", 409)
    try:
        actual = await project_workspace(authorization["projectId"])
    except DomainError as exc:
        raise ToolPreflightError(exc.code, exc.status) from exc
    await database.call(lambda db: assert_dispatch_authorized(db, task, run))
    if (
        actual.get("projectId") != authorization["projectId"]
        or actual.get("directory") != authorization["projectDirectory"]
    ):
        raise ToolPreflightError("SWARM_COORDINATION_WORKSPACE_CHANGED", 409)
