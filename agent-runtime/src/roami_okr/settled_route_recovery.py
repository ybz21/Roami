"""Recover an original coordination batch after a verified native refusal."""

import re

from roami_agent.conversation.idle import assert_main_idle
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row, rows
from roami_agent.storage.swarm_coordination_admission import batch_context
from roami_agent.storage.swarm_model_wait import queue_route_retry

_RECOVERABLE_NATIVE_TURNS = (
    "FROM swarm_coordination_batches b JOIN turns t ON t.id=b.turn_id "
    "JOIN conversations c ON c.id=t.conversation_id AND c.active_branch_id=t.branch_id "
    "JOIN swarm_groups g ON g.id=b.swarm_id AND g.owner_id=c.owner_id "
    "AND g.conversation_id=c.id AND g.archived=0 "
    "WHERE t.trigger_kind='continuation' AND c.deleted_ms IS NULL "
    "AND t.id=(SELECT latest.id FROM turns latest WHERE latest.branch_id=c.active_branch_id "
    "ORDER BY latest.created_ms DESC,latest.rowid DESC LIMIT 1) "
    "AND EXISTS(SELECT 1 FROM events e WHERE e.turn_id=t.id AND ("
    "(t.state='failed' AND e.kind='turn.failed' "
    "AND json_extract(e.payload_json,'$.error')='PROJECT_MAIN_EXECUTION_FAILED') OR "
    "(t.state='interrupted' AND e.kind='turn.interrupted' "
    "AND json_extract(e.payload_json,'$.reason')='runtime_restart' "
    "AND e.id=(SELECT MAX(last.id) FROM events last WHERE last.turn_id=t.id "
    "AND last.kind='turn.interrupted')))) "
)


def recovery_candidates(db):
    return rows(
        db,
        "SELECT t.id,t.conversation_id,c.owner_id "
        + _RECOVERABLE_NATIVE_TURNS
        + "AND EXISTS(SELECT 1 FROM project_okr_main_providers p WHERE p.conversation_id=c.id "
        "AND p.owner_id=c.owner_id AND p.executor='claude')",
    )


def recover_route_wait(db, turn_id, model, proof):
    turn = row(
        db,
        "SELECT t.*,c.owner_id,b.id AS batch_id "
        + _RECOVERABLE_NATIVE_TURNS
        + "AND t.id=? AND t.conversation_id=? AND c.owner_id=?",
        (turn_id, model.binding["conversation_id"], model.binding["owner_id"]),
    )
    if not turn:
        return False
    job = row(
        db,
        "SELECT id,attempts,COALESCE(json_extract(payload_json,'$.nativeRouteRetry'),0) AS generation "
        "FROM jobs WHERE kind='turn.run' AND aggregate_id=? AND state='failed' "
        "AND json_extract(payload_json,'$.coordinationBatchId')=? "
        "AND COALESCE(json_type(payload_json,'$.nativeRouteRetry'),'integer')='integer' "
        "AND json_extract(payload_json,'$.completion') IS NULL",
        (turn_id, turn["batch_id"]),
    )
    if not job or job["generation"] < 0 or job["attempts"] != job["generation"] + 1:
        return False
    generation = job["generation"]
    legacy = turn["state"] == "failed"
    if legacy and generation != 0:
        return False
    refusal = proof.get("routeRefusal")
    if not isinstance(refusal, dict):
        return False
    launch_key = refusal.get("launchKey")
    code, digest, finished = (
        refusal.get("code"),
        refusal.get("stopEvidenceSha256"),
        refusal.get("finishedMs"),
    )
    expected_key = "project-main:" + re.escape(turn_id) + r":[a-f0-9]{24}"
    if generation:
        expected_key += f":retry-{generation}"
    if (
        not isinstance(launch_key, str)
        or not re.fullmatch(expected_key, launch_key)
        or code not in ("MODEL_ROUTE_NO_AVAILABLE_MEMBER", "CLAUDE_COMPACTION_FAILED")
        or not isinstance(digest, str)
        or not re.fullmatch(r"[a-f0-9]{64}", digest)
        or type(finished) is not int
        or turn["finished_ms"] is None
        or not turn["created_ms"] <= finished <= turn["finished_ms"]
    ):
        return False
    manifest = row(
        db,
        "SELECT attempt_no,COUNT(*) OVER () AS manifest_count,provider_key,model_key,created_ms,"
        "json_extract(parts_json,'$.modelSettingsHash') AS model_hash,"
        "json_extract(parts_json,'$.timing.errorCode') AS error,json_extract(parts_json,'$.timing.state') AS state,"
        "json_extract(parts_json,'$.timing.modelStartedMs') AS model_started,"
        "json_extract(parts_json,'$.timing.firstTextMs') AS first_text "
        "FROM prompt_manifests WHERE turn_id=? ORDER BY attempt_no DESC LIMIT 1",
        (turn_id,),
    )
    if (
        not manifest
        or manifest["manifest_count"] != job["attempts"]
        or manifest["attempt_no"] != job["attempts"]
        or manifest["provider_key"] != model.provider_key
        or manifest["model_key"] != model.model
        or manifest["model_hash"] != model.settings_hash
        or manifest["first_text"] is not None
        or manifest["created_ms"] > finished
        or row(db, "SELECT 1 FROM tool_calls WHERE turn_id=? LIMIT 1", (turn_id,))
        or row(
            db,
            "SELECT 1 FROM messages WHERE turn_id=? AND role='assistant' AND status='completed'",
            (turn_id,),
        )
    ):
        return False
    timing = (manifest["state"], manifest["error"])
    if legacy:
        valid_timing = timing == ("failed", "PROJECT_MAIN_EXECUTION_FAILED")
    else:
        started = manifest["model_started"]
        valid_timing = (
            type(started) is int
            and manifest["created_ms"] <= started <= finished
            and timing in {("running", None), ("failed", code)}
        )
    if not valid_timing:
        return False
    conversation = row(db, "SELECT * FROM conversations WHERE id=?", (turn["conversation_id"],))
    assert_main_idle(db, conversation)
    assert_context_admitted(db, {"id": turn_id, "owner_id": turn["owner_id"]})
    queue_route_retry(db, turn, job["id"], generation, code, digest)
    batch_context(db, turn["owner_id"], turn_id, allow_paused=True)
    return True
