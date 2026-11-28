"""Rebind a stopped member to a prepared instance of the same native conversation."""

import json

from roami_agent.dispatch.swarm_member_model_selection import MemberModelSelections
from roami_agent.dispatch.swarm_provider_generations import (
    PreparationRequired,
    bind_prepared_member,
    validate_prepared_member,
)
from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.protocol.errors import DomainError
from roami_agent.providers.native_conversation import NativeConversation
from roami_agent.storage.database import event, row, rows
from roami_agent.storage.swarm_repository import changed, group, receipt


def unsubmitted_attempt(run):
    return (
        bool(run["launch_id"])
        and run["executor_kind"] == "cli"
        and run["session_id"] is None
        and run["agent_conversation_id"] is None
        and run["state"] == "failed"
        and run["finished_ms"] is not None
        and json.loads(run["result_json"] or "{}")
        == {"state": "failed", "summary": "CODING_EXECUTOR_NOT_STARTED"}
    )


def recovery_source(db, owner, sid, mid, spec):
    run = row(db, "SELECT * FROM task_attempts WHERE id=?", (spec["expectedRunId"],))
    if not run or run["task_id"] != spec["taskId"] or not run["launch_id"]:
        raise DomainError("SWARM_PROVIDER_RECOVERY_UNCONFIRMED", 409)
    unsubmitted = unsubmitted_attempt(run)
    team, work, provider = MemberModelSelections.binding(
        db, owner, sid, mid, spec, unsubmitted_run=run["id"] if unsubmitted else None
    )
    if not unsubmitted:
        return team, work, provider, run["launch_id"], []
    source = row(
        db,
        "SELECT attempt_no,launch_id,session_id,agent_conversation_id FROM task_attempts "
        "WHERE task_id=? AND attempt_no<? AND session_id IS NOT NULL "
        "ORDER BY attempt_no DESC LIMIT 1",
        (run["task_id"], run["attempt_no"]),
    )
    if (
        not source
        or not source["launch_id"]
        or source["session_id"] != provider["session_id"]
        or source["agent_conversation_id"] != provider["provider_id"]
    ):
        raise DomainError("SWARM_PROVIDER_RECOVERY_UNCONFIRMED", 409)
    later = rows(
        db,
        "SELECT * FROM task_attempts WHERE task_id=? AND attempt_no>? ORDER BY attempt_no",
        (run["task_id"], source["attempt_no"]),
    )
    if not all(unsubmitted_attempt(attempt) for attempt in later):
        raise DomainError("SWARM_PROVIDER_RECOVERY_UNCONFIRMED", 409)
    return team, work, provider, source["launch_id"], later


def verify_recovery(spec, original, source, proof, status):
    binding = json.loads(original["binding_json"])
    validate_prepared_member({**spec, "executor": "claude"}, proof, binding["directory"])
    prepared = proof["sessionBinding"]
    if (
        proof.get("recoveredFrom") != source
        or proof["sessionId"] == original["session_id"]
        or any(
            not binding.get(key) or prepared.get(key) != binding[key]
            for key in (
                "providerConversationId",
                "hostProof",
                "directory",
                "directoryProof",
                "providerHome",
                "providerHomeProof",
            )
        )
        or prepared.get("providerHomeExplicit") != binding.get("providerHomeExplicit")
    ):
        raise DomainError("SWARM_PROVIDER_RECOVERY_UNCONFIRMED", 409)
    NativeConversation({**original, "binding": binding}, {}, None).verify(status)
    result = status.get("result")
    if (
        not isinstance(result, dict)
        or result.get("state") not in {"succeeded", "failed", "cancelled"}
        or result.get("state") != status.get("state")
        or result.get("inputStopped") is not True
        or result.get("outcomeKnown") is not True
    ):
        raise DomainError("SWARM_PROVIDER_RECOVERY_UNCONFIRMED", 409)


async def recover_member(swarms, owner, sid, mid, spec):
    database = swarms.db
    command = {"swarmId": sid, "memberId": mid, **spec}

    def apply_receipt(db, apply):
        group(db, owner, sid)
        return receipt(db, owner, spec["commandKey"], command, apply, swarm_id=sid)

    def pending():
        raise PreparationRequired

    async with swarms.lock(sid):
        try:
            return await database.call(lambda db: apply_receipt(db, pending))
        except PreparationRequired:
            pass
        _, work, original, source, unsubmitted = await database.call(
            lambda db: recovery_source(db, owner, sid, mid, spec)
        )
        if swarms.settings is None:
            raise DomainError("SWARM_PREPARATION_UNAVAILABLE", 409)
        observer = CodingExecutor(database, swarms.settings)
        proof = await observer.command("prepared", "--key", spec["preparedLaunchKey"])
        status = await observer.command("status", "--key", source)
        verify_recovery(spec, original, source, proof, status)
        for attempt in unsubmitted:
            if await observer.command("status", "--key", attempt["launch_id"]) != {
                "state": "not_started"
            }:
                raise DomainError("SWARM_PROVIDER_RECOVERY_UNCONFIRMED", 409)

        def write(db):
            def apply():
                team, current_work, current, current_source, current_unsubmitted = recovery_source(
                    db, owner, sid, mid, spec
                )
                if (
                    current != original
                    or current_work["id"] != work["id"]
                    or current_source != source
                    or current_unsubmitted != unsubmitted
                ):
                    raise DomainError("SWARM_MEMBER_MODEL_BINDING_CHANGED", 409)
                generation = current["generation"] + 1
                db.execute(
                    "UPDATE swarm_members SET execution_generation=?,model=? WHERE id=?",
                    (generation, spec["model"], mid),
                )
                bind_prepared_member(
                    db,
                    team,
                    {"id": mid},
                    generation,
                    proof,
                    check_reserved_provider=swarms.check_reserved_provider,
                )
                db.execute(
                    "UPDATE swarm_work_items SET execution_generation=?,model=? WHERE id=?",
                    (generation, spec["model"], work["id"]),
                )
                for attempt in unsubmitted:
                    event(
                        db,
                        team["conversation_id"],
                        "task.execution_not_started_confirmed",
                        {"runId": attempt["id"], "launchId": attempt["launch_id"]},
                        task_id=spec["taskId"],
                        key="execution-not-started:" + attempt["id"],
                    )
                db.execute("UPDATE swarm_groups SET revision=revision+1 WHERE id=?", (sid,))
                team["revision"] += 1
                changed(db, team, "swarm.member_provider_recovered")
                return {
                    "memberId": mid,
                    "taskId": spec["taskId"],
                    "taskRevision": spec["expectedTaskRevision"],
                    "generation": generation,
                    "model": spec["model"],
                    "sessionId": proof["sessionId"],
                    "revision": team["revision"],
                }

            return apply_receipt(db, apply)

        return await database.call(write, write=True)
