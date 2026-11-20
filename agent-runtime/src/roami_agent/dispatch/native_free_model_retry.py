"""Reschedule a native task once, with no sent model request or executed tools."""

import json

from roami_agent.conversation.activity_events import activity_event as event
from roami_agent.executors.task_directory import automatic_task_directory
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row


def defer_free_model(db, task, run, turn, job_id, retry_at):
    if not turn or run["executor_kind"] != "native":
        return False
    now = now_ms()
    if retry_at <= now:
        return False
    current = row(
        db,
        "SELECT * FROM tasks WHERE id=? AND revision=? AND state='running'",
        (task["id"], run["task_revision"]),
    )
    if not current:
        return False
    intent = json.loads(current["intent_json"])
    target = intent["target"]
    if not intent.get("freeOnly") or not (
        automatic_task_directory(target) or target.get("resourceOnly") is True
    ):
        return False
    deadline = json.loads(current["budget_json"]).get("deadlineMs")
    if deadline and retry_at >= deadline:
        return False
    job = row(db, "SELECT * FROM jobs WHERE id=? AND state='running'", (job_id,))
    if not job:
        return False
    payload = json.loads(job["payload_json"])
    if payload.get("freeModelRetryAtMs") or payload.get("runId") != run["id"]:
        return False
    active = row(
        db,
        "SELECT id FROM task_attempts WHERE id=? AND task_id=? AND task_revision=? "
        "AND state='running' AND result_json IS NULL "
        "AND NOT EXISTS(SELECT 1 FROM resource_actions WHERE run_id=task_attempts.id) "
        "AND NOT EXISTS(SELECT 1 FROM resource_observations WHERE run_id=task_attempts.id)",
        (run["id"], current["id"], current["revision"]),
    )
    untouched = row(
        db,
        "SELECT id FROM turns WHERE id=? AND branch_id=? AND state='running' AND lease_epoch=? "
        "AND NOT EXISTS(SELECT 1 FROM tool_calls WHERE turn_id=turns.id) "
        "AND NOT EXISTS(SELECT 1 FROM messages WHERE turn_id=turns.id AND role!='user' AND deleted_ms IS NULL) "
        "AND (SELECT COUNT(*) FROM messages WHERE turn_id=turns.id AND role='user' AND deleted_ms IS NULL)=1",
        (turn["id"], run["native_branch_id"], turn["lease_epoch"]),
    )
    if not active or not untouched:
        return False
    restore_task_step(db, current)
    # Restore the unstarted input; the existing runner binds it to the next turn.
    db.execute("UPDATE messages SET turn_id=NULL WHERE turn_id=? AND role='user'", (turn["id"],))
    db.execute("UPDATE turns SET state='interrupted',finished_ms=? WHERE id=?", (now, turn["id"]))
    db.execute("UPDATE tasks SET state='queued',updated_ms=? WHERE id=?", (now, current["id"]))
    db.execute("UPDATE task_attempts SET state='accepted' WHERE id=?", (run["id"],))
    payload["freeModelRetryAtMs"] = retry_at
    db.execute(
        "UPDATE jobs SET state='queued',available_ms=?,payload_json=? WHERE id=?",
        (retry_at, encoded(payload), job_id),
    )
    event(
        db,
        turn["conversation_id"],
        "turn.interrupted",
        {"turnId": turn["id"], "error": "MODEL_ROUTE_NO_AVAILABLE_MEMBER"},
        turn_id=turn["id"],
    )
    event(
        db,
        current["origin_conversation_id"],
        "task.waiting_for_free_model",
        {"taskId": current["id"], "runId": run["id"], "modelRetryAtMs": retry_at},
        task_id=current["id"],
    )
    return True


def restore_task_step(db, task):
    while task:
        budget = json.loads(task["budget_json"])
        if budget.get("usedSteps", 0) > 0:
            budget["usedSteps"] -= 1
            db.execute("UPDATE tasks SET budget_json=? WHERE id=?", (encoded(budget), task["id"]))
        parent_id = task["parent_task_id"]
        task = row(db, "SELECT * FROM tasks WHERE id=?", (parent_id,)) if parent_id else None


def queued_free_model_retry(db, task):
    attempt = task["latestAttempt"]
    if task["state"] != "queued" or not attempt or attempt["executorKind"] != "native":
        return None
    waiting = row(
        db,
        "SELECT json_extract(j.payload_json,'$.freeModelRetryAtMs') AS retry_at "
        "FROM jobs j JOIN task_attempts a ON a.id=json_extract(j.payload_json,'$.runId') "
        "WHERE j.dedupe_key=? AND j.aggregate_id=? AND j.kind='task.run' AND j.state='queued' "
        "AND a.task_revision=? AND a.state='accepted' AND a.executor_kind='native' "
        "AND json_type(j.payload_json,'$.freeModelRetryAtMs')='integer' LIMIT 1",
        ("run:" + attempt["runId"], task["id"], task["revision"]),
    )
    return waiting["retry_at"] if waiting else None
