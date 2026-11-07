"""Recognize only this Main turn's audited review of its waiting completion."""

import json

from roami_agent.storage.database import row


def self_verified_completion(db, turn, source):
    if source.get("state") != "waiting_user" or turn.get("executionRunId"):
        return None
    context = row(
        db,
        "SELECT t.conversation_id FROM turns t JOIN conversations c ON c.id=t.conversation_id "
        "WHERE t.id=? AND c.owner_id=? AND c.deleted_ms IS NULL",
        (turn["id"], turn["owner_id"]),
    )
    if (
        not context
        or turn.get("conversation_id", context["conversation_id"]) != context["conversation_id"]
    ):
        return None
    conversation_id = context["conversation_id"]
    task_id = source.get("taskId")
    revision = source.get("taskRevision", source.get("revision", 1))
    run_id = source.get("runId")
    if not run_id:
        job = row(
            db,
            "SELECT payload_json FROM jobs WHERE kind='turn.run' AND aggregate_id=?",
            (turn["id"],),
        )
        original = json.loads(job["payload_json"]).get("completion", {}) if job else {}
        if (
            original.get("taskId") != task_id
            or original.get("taskRevision", 1) != revision
            or original.get("state") != "waiting_user"
        ):
            return None
        run_id = original.get("runId")
    if not isinstance(run_id, str) or not run_id:
        return None
    task = row(
        db,
        "SELECT t.* FROM tasks t JOIN messages m ON m.id=t.origin_message_id "
        "JOIN conversations c ON c.id=t.origin_conversation_id "
        "WHERE t.id=? AND t.owner_id=? AND t.revision=? AND t.origin_conversation_id=? "
        "AND t.state IN ('succeeded','failed') AND m.deleted_ms IS NULL "
        "AND c.deleted_ms IS NULL AND c.owner_id=t.owner_id "
        "AND NOT EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=t.owner_id AND o.message_id=m.id) "
        "AND NOT EXISTS(SELECT 1 FROM jobs j WHERE j.kind='task.steer' AND j.aggregate_id=t.id AND j.state='queued') "
        "AND NOT EXISTS(SELECT 1 FROM jobs j WHERE j.kind='control.stop' AND json_extract(j.payload_json,'$.turnId')=?)",
        (task_id, turn["owner_id"], revision, conversation_id, turn["id"]),
    )
    latest = row(
        db,
        "SELECT id FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
        (task_id, revision),
    )
    if not task or not latest or latest["id"] != run_id:
        return None
    audit = row(
        db,
        "SELECT e.id,e.payload_json FROM events e JOIN swarm_groups g "
        "ON g.id=json_extract(e.payload_json,'$.swarmId') "
        "JOIN swarm_work_items w ON w.swarm_id=g.id AND w.task_id=e.task_id "
        "WHERE e.kind='swarm.verification_recorded' AND e.task_id=? "
        "AND e.turn_id=? AND e.conversation_id=? AND g.owner_id=? AND g.conversation_id=e.conversation_id "
        "AND json_extract(e.payload_json,'$.reviewer')='main' "
        "AND json_extract(e.payload_json,'$.mainConversationId')=e.conversation_id "
        "AND json_extract(e.payload_json,'$.mainTurnId')=e.turn_id "
        "AND json_extract(e.payload_json,'$.taskId')=e.task_id "
        "AND json_extract(e.payload_json,'$.revision')=? "
        "AND json_extract(e.payload_json,'$.runId')=? ORDER BY e.id DESC LIMIT 1",
        (task_id, turn["id"], conversation_id, turn["owner_id"], revision, run_id),
    )
    if not audit:
        return None
    decision = json.loads(audit["payload_json"]).get("accepted")
    if type(decision) is not bool or task["state"] != ("succeeded" if decision else "failed"):
        return None
    terminal = row(
        db,
        "SELECT payload_json FROM events WHERE task_id=? AND conversation_id=? AND kind=? "
        "AND json_extract(payload_json,'$.taskId')=? AND json_extract(payload_json,'$.taskRevision')=? "
        "AND json_extract(payload_json,'$.runId')=? AND json_extract(payload_json,'$.state')=? "
        "AND id<? ORDER BY id DESC LIMIT 1",
        (
            task_id,
            conversation_id,
            "task." + task["state"],
            task_id,
            revision,
            run_id,
            task["state"],
            audit["id"],
        ),
    )
    return json.loads(terminal["payload_json"]) if terminal else None
