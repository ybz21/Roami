"""Prove the original member's applied execution identity; this grants no publish rights."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.swarm_coordination_tasks import assert_dispatch_authorized
from roami_agent.storage.swarm_delegations import current_delegation


def publisher_identity(db, owner, scope, actor):
    if (
        type(actor.get("revision")) is not int
        or actor["revision"] < 1
        or type(scope.get("steerSourceRevision")) is not int
        or scope["steerSourceRevision"] < 1
    ):
        raise DomainError("INVALID_PUBLICATION_EXECUTION_IDENTITY")
    goal = current_delegation(db, owner, scope["swarmId"], scope["delegationId"])
    if goal["projectId"] != scope["projectId"] or scope["memberId"] not in json.loads(
        goal["member_ids_json"]
    ):
        raise DomainError("PUBLICATION_PROJECT_SCOPE_CONFLICT", 403)
    task = row(
        db,
        "SELECT t.* FROM swarm_members m JOIN swarm_member_work b ON b.member_id=m.id AND b.work_id=m.current_work_id JOIN swarm_work_items w ON w.id=b.work_id AND w.swarm_id=m.swarm_id JOIN tasks t ON t.id=w.task_id WHERE m.id=? AND m.swarm_id=? AND t.id=? AND t.owner_id=? AND t.origin_conversation_id=?",
        (scope["memberId"], scope["swarmId"], scope["taskId"], owner, goal["mainConversationId"]),
    )
    run = row(
        db,
        "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
        (scope["taskId"], actor["revision"]),
    )
    if (
        not task
        or not run
        or actor["taskId"] != task["id"]
        or task["revision"] != actor["revision"]
        or run["id"] != actor["runId"]
        or task["state"] != "running"
        or run["state"] != "running"
    ):
        raise DomainError("PUBLICATION_PUBLISHER_NOT_CURRENT", 409)
    authorization = json.loads(task["intent_json"]).get("coordinationAuthorization")
    if (
        not authorization
        or authorization.get("operationId") != scope["operationId"]
        or authorization.get("sourceTaskRevision") != scope["steerSourceRevision"]
        or authorization.get("sourceRunId") != scope["steerSourceRunId"]
        or authorization.get("memberId") != scope["memberId"]
    ):
        raise DomainError("PUBLICATION_OPERATION_SCOPE_CONFLICT", 409)
    job = row(
        db,
        "SELECT * FROM jobs WHERE id=? AND kind='task.steer' AND aggregate_id=? AND state='done'",
        (scope["operationId"], task["id"]),
    )
    payload = json.loads(job["payload_json"]) if job else {}
    if (
        payload.get("status") != "applied"
        or payload.get("appliedRevision") != actor["revision"]
        or payload.get("runId") != actor["runId"]
        or run["launch_id"] != "task-revision:" + scope["operationId"]
    ):
        raise DomainError("PUBLICATION_OPERATION_NOT_APPLIED", 409)
    assert_dispatch_authorized(db, task, run)
    return {
        "projectId": scope["projectId"],
        "swarmId": scope["swarmId"],
        "memberId": scope["memberId"],
        "taskId": task["id"],
        "revision": actor["revision"],
        "runId": run["id"],
        "operationId": job["id"],
    }
