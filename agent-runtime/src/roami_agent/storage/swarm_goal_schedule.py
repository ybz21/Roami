"""Bind an explicit scheduled wait to settled original work and the current goal lease."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.storage.database import row, rows
from roami_agent.storage.swarm_goal_checkpoint import (
    active_next_steps,
    checkpoint_context,
    stored_checkpoint,
)
from roami_agent.storage.swarm_repository import receipt

PREFIX = "goal-scheduled-wait:"


def wait_context(db, binding):
    value = checkpoint_context(db, binding)
    if value is None:
        raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
    goal = value["delegation"]
    if active_next_steps(db, binding)["steps"]:
        raise DomainError("SWARM_GOAL_WORK_UNSETTLED", 409)
    members = json.loads(goal["member_ids_json"])
    tasks = rows(
        db,
        "SELECT m.id AS member_id,t.id,t.revision,t.state FROM swarm_members m "
        "JOIN swarm_work_items w ON w.id=m.current_work_id JOIN tasks t ON t.id=w.task_id "
        "WHERE m.swarm_id=? AND m.id IN (SELECT value FROM json_each(?)) "
        "AND t.owner_id=? AND t.origin_conversation_id=? ORDER BY m.id",
        (value["swarm_id"], goal["member_ids_json"], binding["owner"], binding["conversation"]),
    )
    settled = []
    if not members or len(tasks) != len(members):
        raise DomainError("SWARM_GOAL_WORK_UNSETTLED", 409)
    for task in tasks:
        run = row(
            db,
            "SELECT id,state,finished_ms FROM task_attempts WHERE task_id=? AND task_revision=? "
            "ORDER BY attempt_no DESC LIMIT 1",
            (task["id"], task["revision"]),
        )
        if (
            task["state"] != "succeeded"
            or not run
            or run["state"] != "succeeded"
            or run["finished_ms"] is None
        ):
            raise DomainError("SWARM_GOAL_WORK_UNSETTLED", 409)
        settled.append(
            {
                "memberId": task["member_id"],
                "taskId": task["id"],
                "revision": task["revision"],
                "runId": run["id"],
            }
        )
    unanswered = row(
        db,
        "SELECT i.id FROM swarm_inbox i JOIN swarm_post_routes r ON r.post_id=i.post_id "
        "JOIN swarm_posts p ON p.id=i.post_id JOIN tasks t ON t.id=p.task_id "
        "WHERE i.main_conversation_id=? AND r.swarm_id=? AND i.handled_post_id IS NULL "
        "AND r.author_kind='member' AND r.author_member_id IN (SELECT value FROM json_each(?)) "
        "AND t.id IN (SELECT value FROM json_each(?)) "
        "AND r.source_task_revision=t.revision AND r.source_run_id=(SELECT a.id "
        "FROM task_attempts a WHERE a.task_id=t.id AND a.task_revision=t.revision "
        "ORDER BY a.attempt_no DESC LIMIT 1) LIMIT 1",
        (
            binding["conversation"],
            value["swarm_id"],
            goal["member_ids_json"],
            json.dumps([t["id"] for t in tasks]),
        ),
    )
    if unanswered:
        raise DomainError("SWARM_GOAL_WORK_UNSETTLED", 409)
    return {
        "batchId": value["id"],
        "delegationRevision": goal["revision"],
        "sourceSha256": goal["source_sha256"],
        "leaseEpoch": value["lease_epoch"],
        "scope": {
            "projectId": goal["projectId"],
            "mainConversationId": binding["conversation"],
            "swarmId": value["swarm_id"],
            "delegationId": goal["id"],
        },
        "tasks": settled,
    }


def proposal(db, binding):
    value = checkpoint_context(db, binding)
    if value is None:
        return None
    return stored_checkpoint(db, binding, value, PREFIX)


def save_wait(db, binding, context, reason, schedule):
    if schedule["nextDueMs"] <= now_ms():
        raise DomainError("GOAL_SCHEDULE_NOT_FUTURE", 409)
    if wait_context(db, binding) != context:
        raise DomainError("SWARM_GOAL_CHECKPOINT_CHANGED", 409)
    payload = {**context, "reason": reason, "schedule": schedule}
    return receipt(
        db,
        binding["owner"],
        PREFIX + context["batchId"] + ":" + str(context["leaseEpoch"]),
        payload,
        lambda: {"kind": "scheduled_goal_wait", "goalComplete": False, **payload},
        swarm_id=context["scope"]["swarmId"],
    )


def check_wait(db, binding, previous):
    context = wait_context(db, binding)
    if any(previous.get(k) != v for k, v in context.items()) or proposal(db, binding) != previous:
        raise DomainError("SWARM_GOAL_CHECKPOINT_CHANGED", 409)
    if previous["schedule"]["nextDueMs"] <= now_ms():
        raise DomainError("GOAL_SCHEDULE_NOT_FUTURE", 409)
