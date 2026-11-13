"""Keep in-flight forgotten context from starting another model or tool operation."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.storage.database import row, rows
from roami_agent.storage.swarm_completion import self_verified_completion


def assert_context_sources_available(db, turn):
    if row(
        db,
        "SELECT 1 FROM context_omissions o WHERE o.owner_id=? AND ("
        "o.message_id IN (SELECT id FROM messages WHERE turn_id=?) OR "
        "o.message_id IN (SELECT j.value FROM prompt_manifests p JOIN json_each(p.parts_json,'$.sourceMessageIds') j WHERE p.turn_id=?)) LIMIT 1",
        (turn["owner_id"], turn["id"], turn["id"]),
    ):
        raise DomainError("CONTEXT_SOURCE_FORGOTTEN", 409)
    if row(
        db,
        "SELECT 1 FROM prompt_manifests p JOIN json_each(p.parts_json,'$.imageEvidence') image "
        "LEFT JOIN artifacts a ON a.id=json_extract(image.value,'$.artifactId') "
        "WHERE p.turn_id=? AND (a.id IS NULL OR a.deleted_ms IS NOT NULL OR a.owner_id!=? "
        "OR EXISTS(SELECT 1 FROM memory_tombstones t WHERE t.owner_id=? AND t.source_fingerprint=a.sha256)) LIMIT 1",
        (turn["id"], turn["owner_id"], turn["owner_id"]),
    ):
        raise DomainError("CONTEXT_SOURCE_FORGOTTEN", 409)

    if row(
        db,
        "SELECT 1 FROM prompt_manifests p JOIN json_each(p.parts_json,'$.attachmentEvidence') attachment "
        "LEFT JOIN artifacts a ON a.id=json_extract(attachment.value,'$.artifactId') "
        "WHERE p.turn_id=? AND (a.id IS NULL OR a.deleted_ms IS NOT NULL OR a.owner_id!=? "
        "OR EXISTS(SELECT 1 FROM memory_tombstones t WHERE t.owner_id=? AND t.source_fingerprint=a.sha256)) LIMIT 1",
        (turn["id"], turn["owner_id"], turn["owner_id"]),
    ):
        raise DomainError("CONTEXT_SOURCE_FORGOTTEN", 409)

    if row(
        db,
        "SELECT 1 FROM prompt_manifests p JOIN json_each(p.parts_json,'$.memoryEvidence') evidence "
        "LEFT JOIN memory_records r ON r.id=json_extract(evidence.value,'$.memoryId') "
        "WHERE p.turn_id=? AND (r.id IS NULL OR r.owner_id!=? OR r.state!='active' "
        "OR r.revision!=json_extract(evidence.value,'$.revision') "
        "OR r.valid_from_ms>? "
        "OR (r.valid_until_ms IS NOT NULL AND r.valid_until_ms<=?) "
        "OR (r.expires_ms IS NOT NULL AND r.expires_ms<=?)) LIMIT 1",
        (turn["id"], turn["owner_id"], now_ms(), now_ms(), now_ms()),
    ):
        raise DomainError("CONTEXT_SOURCE_FORGOTTEN", 409)


def assert_context_admitted(db, turn):
    if turn.get("trigger_kind") == "continuation" and row(
        db,
        "SELECT name FROM sqlite_master WHERE type='table' AND name='swarm_coordination_batches'",
    ):
        from roami_agent.storage.swarm_coordination_admission import for_turn

        for_turn(db, turn)
    if row(
        db,
        "SELECT 1 FROM jobs WHERE kind IN ('control.stop','control.pause') "
        "AND json_extract(payload_json,'$.turnId')=? LIMIT 1",
        (turn["id"],),
    ):
        raise DomainError("TURN_INTERRUPTED", 409)
    from roami_agent.storage.swarm_work_pause import conversation_paused

    current = row(db, "SELECT conversation_id FROM turns WHERE id=?", (turn["id"],))
    if current and conversation_paused(db, current["conversation_id"]):
        raise DomainError("TURN_INTERRUPTED", 409)
    assert_context_sources_available(db, turn)

    if row(
        db,
        "SELECT 1 FROM prompt_manifests p LEFT JOIN tasks t ON t.id=json_extract(p.parts_json,'$.taskEvidence.taskId') "
        "WHERE p.turn_id=? AND json_type(p.parts_json,'$.taskEvidence')='object' "
        "AND (t.id IS NULL OR t.owner_id!=? OR t.revision!=json_extract(p.parts_json,'$.taskEvidence.revision') "
        "OR EXISTS(SELECT 1 FROM jobs j WHERE j.kind='task.steer' AND j.aggregate_id=t.id AND j.state='queued')) LIMIT 1",
        (turn["id"], turn["owner_id"]),
    ):
        raise DomainError("TASK_RESULT_SUPERSEDED", 409)

    for manifest in rows(
        db,
        "SELECT json_extract(p.parts_json,'$.taskEvidence') AS evidence FROM prompt_manifests p "
        "JOIN tasks t ON t.id=json_extract(p.parts_json,'$.taskEvidence.taskId') "
        "WHERE p.turn_id=? AND t.state!=json_extract(p.parts_json,'$.taskEvidence.state')",
        (turn["id"],),
    ):
        if not self_verified_completion(db, turn, json.loads(manifest["evidence"])):
            raise DomainError("TASK_RESULT_SUPERSEDED", 409)
