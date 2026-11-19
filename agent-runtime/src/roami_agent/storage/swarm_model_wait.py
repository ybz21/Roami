"""Requeue the same coordination batch after a proven native route refusal."""

import json
import re

from roami_agent.protocol.identity import now_ms
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import event, row
from roami_agent.storage.reply_previews import clear_reply_previews
from roami_agent.storage.swarm_coordination_admission import for_turn

RETRY_DELAYS_MS = (60_000, 180_000, 600_000, 900_000)


def defer_native_route(db, turn, code, stop_evidence):
    if turn.get("trigger_kind") != "continuation" or not re.fullmatch(
        r"[a-f0-9]{64}", stop_evidence
    ):
        return False
    batch = for_turn(db, turn, allow_paused=True)
    if batch is None:
        return False
    assert_context_admitted(db, turn, allow_coordination_paused=True)
    job = row(
        db,
        "SELECT id,payload_json FROM jobs WHERE kind='turn.run' AND aggregate_id=? "
        "AND state='running' AND json_extract(payload_json,'$.coordinationBatchId')=?",
        (turn["id"], batch["id"]),
    )
    if not job or row(db, "SELECT 1 FROM tool_calls WHERE turn_id=? LIMIT 1", (turn["id"],)):
        return False
    if row(
        db,
        "SELECT 1 FROM messages WHERE turn_id=? AND role='assistant' AND status='completed' LIMIT 1",
        (turn["id"],),
    ):
        return False
    generation = json.loads(job["payload_json"]).get("nativeRouteRetry", 0)
    retry_at = now_ms() + RETRY_DELAYS_MS[min(generation, len(RETRY_DELAYS_MS) - 1)]
    db.execute(
        "UPDATE messages SET status='interrupted' WHERE turn_id=? AND status='streaming'",
        (turn["id"],),
    )
    clear_reply_previews(db, turn["id"])
    db.execute("UPDATE turns SET state='queued' WHERE id=?", (turn["id"],))
    db.execute(
        "UPDATE jobs SET state='queued',available_ms=?,"
        "payload_json=json_set(payload_json,'$.nativeRouteRetry',?) WHERE id=?",
        (retry_at, generation + 1, job["id"]),
    )
    event(
        db,
        turn["conversation_id"],
        "turn.deferred",
        {
            "turnId": turn["id"],
            "reason": code,
            "retryAtMs": retry_at,
            "retryGeneration": generation + 1,
            "stopEvidenceSha256": stop_evidence,
        },
        turn_id=turn["id"],
    )
    return True
