"""Transactional cancellation of a task tree and its outstanding verification jobs."""

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import event, row, rows

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


def request_task_cancellation(db, owner, task_id):
    root = row(db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (task_id, owner))
    if not root:
        raise DomainError("TASK_NOT_FOUND", 404)
    children = rows(
        db,
        "WITH RECURSIVE tree(id) AS (SELECT ? UNION ALL "
        "SELECT t.id FROM tasks t JOIN tree ON t.parent_task_id=tree.id) "
        "SELECT t.* FROM tasks t JOIN tree ON tree.id=t.id",
        (task_id,),
    )
    for task in children:
        if task["state"] not in TERMINAL:
            db.execute(
                "UPDATE tasks SET state='cancelling',updated_ms=? WHERE id=?",
                (now_ms(), task["id"]),
            )
            event(
                db,
                task["origin_conversation_id"],
                "task.cancelling",
                {"taskId": task["id"]},
                task_id=task["id"],
            )
            run = row(
                db,
                "SELECT id FROM task_attempts WHERE task_id=? AND task_revision=? "
                "AND result_json IS NOT NULL ORDER BY attempt_no DESC LIMIT 1",
                (task["id"], task["revision"]),
            )
            if run:
                db.execute(
                    "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) "
                    "VALUES(?,'task.verify',?,?,?,'queued',?) "
                    "ON CONFLICT(dedupe_key) DO UPDATE SET state='queued',available_ms=excluded.available_ms "
                    "WHERE jobs.state IN ('done','failed')",
                    (
                        identity(),
                        task["id"],
                        "verify:" + run["id"],
                        encoded({"runId": run["id"]}),
                        now_ms(),
                    ),
                )
    return {
        "taskId": task_id,
        "state": root["state"] if root["state"] in TERMINAL else "cancelling",
    }
