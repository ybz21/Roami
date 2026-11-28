"""Resume an existing daily batch after a confirmed change of Main's model."""

import json
import re

from roami_agent.conversation.idle import assert_main_idle
from roami_agent.dispatch.swarm_provider_generations import validate_prepared_member
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import event, row, rows
from roami_agent.storage.swarm_coordination_admission import batch_context
from roami_agent.storage.swarm_coordination_results import frozen
from roami_agent.storage.swarm_daily_goal import date_slot
from roami_agent.storage.swarm_model_wait import queue_route_retry
from roami_agent.storage.swarm_repository import receipt
from roami_agent.storage.transcript_repository import owned
from roami_okr.intake import assert_project_main

REFUSAL = "MODEL_HTTP_400"
UNCONFIRMED = "PROJECT_MAIN_DAILY_RETRY_UNCONFIRMED"


class ObserveRefusals(Exception):
    pass


def aborted_request(db, turn, model):
    manifest = row(
        db,
        "SELECT provider_key,model_key,created_ms,"
        "json_extract(parts_json,'$.modelSettingsHash') AS model_hash "
        "FROM prompt_manifests WHERE turn_id=? AND attempt_no=1 "
        "AND json_extract(parts_json,'$.timing.state')='failed' "
        "AND json_extract(parts_json,'$.timing.errorCode')='PROJECT_MAIN_EXECUTION_FAILED' "
        "AND json_extract(parts_json,'$.timing.firstTextMs') IS NULL "
        "AND NOT EXISTS(SELECT 1 FROM prompt_manifests x WHERE x.turn_id=? AND x.attempt_no!=1)",
        (turn["id"], turn["id"]),
    )
    if (
        turn["state"] != "failed"
        or turn["finished_ms"] is None
        or not manifest
        or manifest["model_key"] != model.model
        or manifest["provider_key"] != model.provider_key
        or manifest["model_hash"] != model.settings_hash
        or row(db, "SELECT 1 FROM tool_calls WHERE turn_id=? LIMIT 1", (turn["id"],))
        or row(
            db,
            "SELECT 1 FROM messages WHERE turn_id=? AND role='assistant' AND status='completed'",
            (turn["id"],),
        )
    ):
        raise DomainError(UNCONFIRMED, 409)
    keys = rows(
        db,
        "SELECT event_key FROM events WHERE turn_id=? AND conversation_id=? "
        "AND kind='turn.native_delivery' AND json_extract(payload_json,'$.state')='closed' "
        "AND json_extract(payload_json,'$.leaseEpoch')=?",
        (turn["id"], turn["conversation_id"], turn["lease_epoch"]),
    )
    pattern = r"native-delivery:(project-main:" + re.escape(turn["id"]) + r":[a-f0-9]{24}):"
    hit = (
        re.fullmatch(pattern + str(turn["lease_epoch"]) + ":closed", keys[0]["event_key"])
        if len(keys) == 1
        else None
    )
    if not hit:
        raise DomainError(UNCONFIRMED, 409)
    return {"turn": turn, "key": hit[1], "modelStarted": manifest["created_ms"]}


def daily_recovery_context(db, owner, cid, spec):
    from roami_okr.main_execution import main_binding
    from roami_okr.main_model_selection import pending_model_selection
    from roami_okr.native_main import NativeMain

    project = spec["projectId"]
    assert_project_main(db, owner, cid, project)
    conversation = owned(db, owner, cid)
    assert_main_idle(db, conversation)
    current = main_binding(db, owner, cid)
    latest_change = row(
        db,
        "SELECT id,created_ms,payload_json FROM events WHERE conversation_id=? "
        "AND kind='project.main.execution.changed' ORDER BY id DESC LIMIT 1",
        (cid,),
    )
    if (
        not current
        or current["executor"] != "claude"
        or not latest_change
        or pending_model_selection(db, cid)
    ):
        raise DomainError(UNCONFIRMED, 409)
    change = json.loads(latest_change["payload_json"])
    if (
        change.get("commandKey") != spec["modelCommandKey"]
        or change.get("generation") != current["generation"]
        or change.get("sessionId") != current["session_id"]
        or change.get("model") != current["model"]
        or not isinstance(change.get("previousModel"), str)
        or change["previousModel"] == current["model"]
        or not isinstance(change.get("proofSha256"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", change["proofSha256"])
    ):
        raise DomainError(UNCONFIRMED, 409)
    starting = row(
        db,
        "SELECT t.*,t.rowid AS position,b.id AS batch_id,b.delegation_id,j.id AS job_id,"
        "json_extract(j.payload_json,'$.dailySlot') AS slot "
        "FROM turns t JOIN swarm_coordination_batches b ON b.turn_id=t.id "
        "JOIN jobs j ON j.kind='turn.run' AND j.aggregate_id=t.id "
        "AND json_extract(j.payload_json,'$.coordinationBatchId')=b.id "
        "WHERE t.id=? AND t.conversation_id=? AND t.branch_id=? AND t.trigger_kind='continuation' "
        "AND t.state='failed' AND j.state='failed' AND j.attempts=1 "
        "AND json_type(j.payload_json,'$.dailySlot')='object'",
        (spec["turnId"], cid, conversation["active_branch_id"]),
    )
    if not starting:
        raise DomainError(UNCONFIRMED, 409)
    slot = json.loads(starting["slot"])
    if (
        date_slot(starting["delegation_id"], timezone=slot.get("timezone"), slot=slot.get("slot"))
        != slot
    ):
        raise DomainError("SWARM_DAILY_DATE_EXPIRED", 409)

    relevant = rows(
        db,
        "SELECT * FROM turns WHERE conversation_id=? AND branch_id=? "
        "AND (created_ms>? OR created_ms=? AND rowid>=?) ORDER BY created_ms,rowid LIMIT 9",
        (
            cid,
            conversation["active_branch_id"],
            starting["created_ms"],
            starting["created_ms"],
            starting["position"],
        ),
    )
    if (
        not relevant
        or len(relevant) > 8
        or any(
            turn["finished_ms"] is None or turn["finished_ms"] > latest_change["created_ms"]
            for turn in relevant
        )
    ):
        raise DomainError(UNCONFIRMED, 409)
    binding = dict(current)
    binding["binding"] = json.loads(binding.pop("binding_json"))
    old = NativeMain({**binding, "model": change["previousModel"]}, {}, None)
    refusals = [aborted_request(db, turn, old) for turn in relevant]
    assert_context_admitted(db, {"id": starting["id"], "owner_id": owner})
    return {
        "binding": binding,
        "slot": slot,
        "starting": starting,
        "refusals": refusals,
        "modelChangeId": latest_change["id"],
    }


async def retry_daily_after_model_change(executions, owner, cid, spec):
    from roami_okr.native_main import NativeMain

    if not spec["commandKey"].strip():
        raise DomainError("INVALID_REQUEST_KEY")
    project = spec["projectId"]

    def check_receipt(db, apply):
        assert_project_main(db, owner, cid, project)
        return receipt(
            db,
            owner,
            spec["commandKey"],
            {"mainConversationId": cid, **spec},
            apply,
            scope_project_id=project,
        )

    def needs_proof():
        raise ObserveRefusals

    try:
        return await executions.db.call(lambda db: check_receipt(db, needs_proof), write=True)
    except ObserveRefusals:
        pass

    original = await executions.db.call(lambda db: daily_recovery_context(db, owner, cid, spec))
    binding = original["binding"]
    command = executions.executor.command
    native = NativeMain(binding, {}, command)
    prepared = await command("prepared", "--key", binding["launch_key"])
    validate_prepared_member(
        {
            "preparedLaunchKey": binding["launch_key"],
            "executor": "claude",
            "model": binding["model"],
        },
        prepared,
        binding["binding"]["directory"],
    )
    native.verify({"session": prepared["sessionId"], "sessionBinding": prepared["sessionBinding"]})
    refused = {}
    for attempt in original["refusals"]:
        status = await command("status", "--key", attempt["key"])
        native.verify(status)
        result = status.get("result") or {}
        stop = result.get("stopEvidenceSha256")
        finished = result.get("finishedMs")
        if (
            status.get("state") != "failed"
            or result.get("state") != "failed"
            or result.get("errorCode") != REFUSAL
            or result.get("inputStopped") is not True
            or result.get("outcomeKnown") is not True
            or type(finished) is not int
            or not attempt["modelStarted"] <= finished <= attempt["turn"]["finished_ms"]
            or not isinstance(stop, str)
            or not re.fullmatch(r"[a-f0-9]{64}", stop)
        ):
            raise DomainError(UNCONFIRMED, 409)
        refused[attempt["turn"]["id"]] = stop

    def write(db):
        def apply():
            if daily_recovery_context(db, owner, cid, spec) != original:
                raise DomainError(UNCONFIRMED, 409)
            turn = original["starting"]
            queue_route_retry(db, turn, turn["job_id"], 0, REFUSAL, refused[turn["id"]])
            context_end = original["refusals"][-1]["turn"]["id"]
            db.execute(
                "UPDATE jobs SET payload_json=json_set(payload_json,'$.contextThroughTurn',?) WHERE id=?",
                (context_end, turn["job_id"]),
            )
            value = batch_context(db, owner, turn["id"])
            frozen(db, value["id"])
            result = {
                "turnId": turn["id"],
                "batchId": value["id"],
                "dailySlot": original["slot"],
                "model": binding["model"],
                "state": "queued",
            }
            event(
                db,
                cid,
                "project.main.daily_model_retry",
                {
                    **result,
                    "modelChangeId": original["modelChangeId"],
                    "stopEvidence": refused,
                },
                turn_id=turn["id"],
            )
            return result

        return check_receipt(db, apply)

    return await executions.db.call(write, write=True)
