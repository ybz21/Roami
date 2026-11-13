"""Durable team work fences, separate from dispatch-only pauses."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row, rows


def active_pause(db, sid):
    return row(
        db,
        "SELECT * FROM jobs WHERE kind='swarm.work.pause' AND aggregate_id=? AND state='queued' ORDER BY rowid DESC LIMIT 1",
        (sid,),
    )


def conversation_paused(db, cid):
    return (
        row(
            db,
            "SELECT 1 FROM jobs j JOIN swarm_groups g ON g.id=j.aggregate_id "
            "WHERE j.kind='swarm.work.pause' AND j.state='queued' AND g.conversation_id=?",
            (cid,),
        )
        is not None
    )


def task_paused(db, task):
    return (
        row(
            db,
            "WITH RECURSIVE ancestors(id,parent_task_id) AS (SELECT id,parent_task_id FROM tasks WHERE id=? "
            "UNION SELECT t.id,t.parent_task_id FROM tasks t JOIN ancestors a ON t.id=a.parent_task_id) "
            "SELECT 1 FROM jobs j JOIN swarm_groups g ON g.id=j.aggregate_id "
            "WHERE j.kind='swarm.work.pause' AND j.state='queued' AND "
            "(EXISTS(SELECT 1 FROM swarm_work_items w JOIN ancestors a ON a.id=w.task_id WHERE w.swarm_id=g.id) "
            "OR (g.scope_project_id IS NOT NULL AND g.conversation_id=? "
            "AND json_extract(?, '$.projectId')=g.scope_project_id))",
            (task["id"], task["origin_conversation_id"], task["target_json"] or "{}"),
        )
        is not None
    )


def assert_stopped(db, pause):
    payload = json.loads(pause["payload_json"])
    for target in payload["targets"]:
        task = row(db, "SELECT * FROM tasks WHERE id=?", (target["taskId"],))
        if task["revision"] != target["revision"]:
            raise DomainError("TASK_REVISION_CHANGED", 409)
        if task["state"] not in {"cancelled", "interrupted", "failed", "succeeded", "waiting_user"}:
            raise DomainError("SWARM_WORK_STOPPING", 409)
        run = row(
            db,
            "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
            (task["id"], task["revision"]),
        )
        if run:
            from roami_agent.dispatch.task_revisions import TaskRevisions

            if error := TaskRevisions._blocked(
                db, task, run, {"messageId": task["origin_message_id"]}
            ):
                raise DomainError(error, 409)
    if payload.get("mainTurnId"):
        turn = row(db, "SELECT state FROM turns WHERE id=?", (payload["mainTurnId"],))
        if turn and turn["state"] in {"running", "queued"}:
            raise DomainError("SWARM_WORK_STOPPING", 409)
        if row(
            db,
            "SELECT 1 FROM tool_calls WHERE turn_id=? AND effect='write' AND state IN ('planned','running','unknown')",
            (payload["mainTurnId"],),
        ):
            raise DomainError("TASK_OUTCOME_UNRESOLVED", 409)
    return payload


def pause_view(db, sid):
    pause = active_pause(db, sid)
    if not pause:
        return None
    try:
        assert_stopped(db, pause)
        return {"state": "paused"}
    except DomainError as exc:
        return {
            "state": "stopping" if exc.code == "SWARM_WORK_STOPPING" else "blocked",
            "errorCode": exc.code,
        }


def pause_targets(db, team):
    return rows(
        db,
        "SELECT DISTINCT t.id AS taskId,t.revision FROM tasks t WHERE t.owner_id=? "
        "AND t.parent_task_id IS NULL AND (t.state IN ('preparing','running') OR EXISTS("
        "SELECT 1 FROM task_attempts a WHERE a.id=(SELECT latest.id FROM task_attempts latest "
        "WHERE latest.task_id=t.id AND latest.task_revision=t.revision ORDER BY latest.attempt_no DESC LIMIT 1) "
        "AND (a.state='unknown' OR json_extract(a.result_json,'$.inputStopped')=0 "
        "OR json_extract(a.result_json,'$.outcomeKnown')=0))) AND "
        "(EXISTS(SELECT 1 FROM swarm_work_items w WHERE w.swarm_id=? AND w.task_id=t.id) "
        "OR (? IS NOT NULL AND t.origin_conversation_id=? AND json_extract(t.target_json,'$.projectId')=?))",
        (
            team["owner_id"],
            team["id"],
            team["scope_project_id"],
            team["conversation_id"],
            team["scope_project_id"],
        ),
    )
