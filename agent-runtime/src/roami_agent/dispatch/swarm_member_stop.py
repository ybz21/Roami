"""Prove a member task tree has stopped before changing its role or executor."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row, rows


def require_stopped_member_task(
    db, owner, team, task, *, allow_settled_native=False, allow_waiting_review=False, own_job=None
):
    if task["owner_id"] != owner or task["origin_conversation_id"] != team["conversation_id"]:
        raise DomainError("SWARM_MEMBER_BINDING_CONFLICT", 409)
    if task["state"] not in {"succeeded", "failed", "cancelled", "interrupted"} and not (
        allow_waiting_review and task["state"] == "waiting_user"
    ):
        raise DomainError("SWARM_MEMBER_STOP_REQUIRED", 409)
    if row(
        db,
        "WITH RECURSIVE tree(id) AS (SELECT ? UNION ALL SELECT t.id FROM tasks t JOIN tree ON t.parent_task_id=tree.id) SELECT 1 FROM jobs WHERE aggregate_id IN (SELECT id FROM tree) AND state IN ('queued','running') AND kind!='swarm.coordinate' AND id IS NOT ? LIMIT 1",
        (task["id"], own_job),
    ):
        raise DomainError("SWARM_MEMBER_STOP_REQUIRED", 409)
    if row(
        db,
        "WITH RECURSIVE tree(id) AS (SELECT ? UNION ALL SELECT t.id FROM tasks t JOIN tree ON t.parent_task_id=tree.id) SELECT 1 FROM tasks WHERE id IN (SELECT id FROM tree) AND id!=? AND state NOT IN ('succeeded','failed','cancelled','interrupted') LIMIT 1",
        (task["id"], task["id"]),
    ):
        raise DomainError("SWARM_MEMBER_STOP_REQUIRED", 409)
    generations = rows(
        db,
        "WITH RECURSIVE tree(id) AS (SELECT ? UNION ALL SELECT t.id FROM tasks t JOIN tree ON t.parent_task_id=tree.id) SELECT * FROM tasks WHERE id IN (SELECT id FROM tree)",
        (task["id"],),
    )
    for generation in generations:
        latest = row(
            db,
            "SELECT * FROM task_attempts WHERE task_id=? ORDER BY attempt_no DESC LIMIT 1",
            (generation["id"],),
        )
        if not latest:
            if generation["state"] != "cancelled" or generation["target_json"] is not None:
                raise DomainError("SWARM_MEMBER_STOP_UNCONFIRMED", 409)
            continue
        outcome = json.loads(latest["result_json"] or "{}")
        settled_native = (
            allow_settled_native
            and latest["executor_kind"] == "native"
            and latest["finished_ms"] is not None
            and latest["state"] == outcome.get("state") == "succeeded"
            and outcome.get("inputStopped") is not False
            and outcome.get("outcomeKnown") is not False
        )
        if latest["state"] not in {"succeeded", "failed", "cancelled", "interrupted"} or (
            not settled_native
            and (outcome.get("inputStopped") is not True or outcome.get("outcomeKnown") is not True)
        ):
            raise DomainError("SWARM_MEMBER_STOP_UNCONFIRMED", 409)
        if (
            (allow_settled_native or allow_waiting_review)
            and latest["native_branch_id"]
            and row(
                db,
                "SELECT 1 FROM turns WHERE branch_id=? AND state IN ('queued','running') LIMIT 1",
                (latest["native_branch_id"],),
            )
        ):
            raise DomainError("SWARM_MEMBER_STOP_REQUIRED", 409)
    if row(
        db,
        "WITH RECURSIVE tree(id) AS (SELECT ? UNION ALL SELECT t.id FROM tasks t JOIN tree ON t.parent_task_id=tree.id) SELECT 1 FROM resources r JOIN task_attempts a ON a.id=r.owner_run_id WHERE a.task_id IN (SELECT id FROM tree) AND (r.state!='idle' OR r.lease_until_ms IS NOT NULL) LIMIT 1",
        (task["id"],),
    ):
        raise DomainError("SWARM_MEMBER_STOP_REQUIRED", 409)
