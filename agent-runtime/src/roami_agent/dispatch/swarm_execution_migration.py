"""Explicit executor generations preserve member identity and retired task evidence."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.executor_kind import is_executor
from roami_agent.storage.database import row, rows
from roami_agent.storage.swarm_repository import changed, group, receipt


def migrate_members(db, owner, sid, spec, *, prepared=None):
    from roami_agent.dispatch.swarm_provider_generations import bind_prepared_member

    prepared = prepared or {}
    value = group(db, owner, sid)
    items = spec.get("members")
    if not isinstance(items, list) or not items or len(items) > 100:
        raise DomainError("INVALID_SWARM_MEMBERS")

    def apply():
        from roami_agent.dispatch.swarm_plans import SwarmPlans

        SwarmPlans.mutable(value, spec)
        if not value["paused"]:
            raise DomainError("SWARM_MIGRATION_REQUIRES_PAUSE", 409)
        if row(
            db,
            "SELECT id FROM turns WHERE conversation_id=? AND state IN ('queued','running')",
            (value["conversation_id"],),
        ):
            raise DomainError("SWARM_MAIN_BUSY", 409)
        result, seen = [], set()
        for item in items:
            ident = item.get("memberId") if isinstance(item, dict) else None
            executor = item.get("executor") if isinstance(item, dict) else None
            model = item.get("model") if isinstance(item, dict) else None
            if (
                not ident
                or ident in seen
                or not is_executor(executor)
                or model is not None
                and (not isinstance(model, str) or not model.strip() or len(model) > 300)
            ):
                raise DomainError("INVALID_SWARM_MEMBER")
            if executor == "native":
                raise DomainError("SWARM_NATIVE_MIGRATION_UNSUPPORTED", 409)
            seen.add(ident)
            member = row(db, "SELECT * FROM swarm_members WHERE id=? AND swarm_id=?", (ident, sid))
            if not member:
                raise DomainError("SWARM_MEMBER_NOT_FOUND", 404)
            work = row(
                db, "SELECT * FROM swarm_work_items WHERE id=?", (member["current_work_id"],)
            )
            task = (
                row(db, "SELECT * FROM tasks WHERE id=?", (work["task_id"],))
                if work and work["task_id"]
                else None
            )
            if task:
                if (
                    task["owner_id"] != owner
                    or task["origin_conversation_id"] != value["conversation_id"]
                ):
                    raise DomainError("SWARM_MEMBER_BINDING_CONFLICT", 409)
                if task["state"] not in {"succeeded", "failed", "cancelled", "interrupted"}:
                    raise DomainError("SWARM_MEMBER_STOP_REQUIRED", 409)
                if row(
                    db,
                    "WITH RECURSIVE tree(id) AS (SELECT ? UNION ALL SELECT t.id FROM tasks t JOIN tree ON t.parent_task_id=tree.id) SELECT 1 FROM jobs WHERE aggregate_id IN (SELECT id FROM tree) AND state IN ('queued','running') AND kind!='swarm.coordinate' LIMIT 1",
                    (task["id"],),
                ):
                    raise DomainError("SWARM_MEMBER_STOP_REQUIRED", 409)
                if row(
                    db,
                    "WITH RECURSIVE tree(id) AS (SELECT ? UNION ALL SELECT t.id FROM tasks t JOIN tree ON t.parent_task_id=tree.id) SELECT 1 FROM tasks WHERE id IN (SELECT id FROM tree) AND state NOT IN ('succeeded','failed','cancelled','interrupted') LIMIT 1",
                    (task["id"],),
                ):
                    raise DomainError("SWARM_MEMBER_STOP_REQUIRED", 409)
                generations = rows(
                    db,
                    "WITH RECURSIVE tree(id) AS (SELECT ? UNION ALL SELECT t.id FROM tasks t JOIN tree ON t.parent_task_id=tree.id) SELECT * FROM tasks WHERE id IN (SELECT id FROM tree)",
                    (task["id"],),
                )
                attempts = []
                for generation in generations:
                    latest = row(
                        db,
                        "SELECT * FROM task_attempts WHERE task_id=? ORDER BY attempt_no DESC LIMIT 1",
                        (generation["id"],),
                    )
                    if not latest and (
                        generation["state"] != "cancelled" or generation["target_json"] is not None
                    ):
                        raise DomainError("SWARM_MEMBER_STOP_UNCONFIRMED", 409)
                    if latest:
                        attempts.append(latest)
                for attempt in attempts:
                    outcome = json.loads(attempt["result_json"] or "{}")
                    if (
                        attempt["state"] not in {"succeeded", "failed", "cancelled", "interrupted"}
                        or outcome.get("inputStopped") is not True
                        or outcome.get("outcomeKnown") is not True
                    ):
                        raise DomainError("SWARM_MEMBER_STOP_UNCONFIRMED", 409)
                if row(
                    db,
                    "WITH RECURSIVE tree(id) AS (SELECT ? UNION ALL SELECT t.id FROM tasks t JOIN tree ON t.parent_task_id=tree.id) SELECT 1 FROM resources r JOIN task_attempts a ON a.id=r.owner_run_id WHERE a.task_id IN (SELECT id FROM tree) AND (r.state!='idle' OR r.lease_until_ms IS NOT NULL) LIMIT 1",
                    (task["id"],),
                ):
                    raise DomainError("SWARM_MEMBER_STOP_REQUIRED", 409)
            old = {
                "memberId": ident,
                "executor": member["executor"],
                "taskId": task["id"] if task else None,
                "taskRevision": task["revision"] if task else None,
                "model": work["model"] if work else None,
            }
            generation = (
                max(member["execution_generation"], work["execution_generation"] if work else 1) + 1
            )
            proof = prepared.get(ident)
            if item.get("preparedLaunchKey") and not proof:
                raise DomainError("SWARM_PREPARATION_UNCONFIRMED", 409)
            if work:
                db.execute(
                    "UPDATE swarm_work_items SET executor=?,model=?,task_id=NULL,dispatch_error='SWARM_MEMBER_REASSIGN_REQUIRED',required_task_revision=1,execution_generation=? WHERE id=?",
                    (executor, model, generation, work["id"]),
                )
            db.execute(
                "UPDATE swarm_members SET executor=?,model=?,execution_generation=? WHERE id=?",
                (executor, model, generation, ident),
            )
            bind_prepared_member(db, value, member, generation, proof)
            result.append(
                {
                    **old,
                    "previousExecutor": old["executor"],
                    "executor": executor,
                    "model": model,
                    "state": "awaiting_assignment",
                    "generation": generation,
                    "providerSessionId": proof["sessionId"] if proof else None,
                }
            )
        db.execute("UPDATE swarm_groups SET revision=revision+1 WHERE id=?", (sid,))
        value["revision"] += 1
        changed(db, value, "swarm.execution_migrated")
        return {"id": sid, "revision": value["revision"], "paused": True, "members": result}

    return receipt(db, owner, spec["commandKey"], {"swarmId": sid, **spec}, apply, swarm_id=sid)
