"""Explicit user closure, fenced against concurrent task continuation."""

import json

from roami_agent.conversation.activity_events import activity_event as event
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.storage.database import row

STABLE = {"succeeded", "failed", "cancelled", "interrupted", "waiting_user"}


def session_closure(db, task_id):
    return row(db, "SELECT * FROM task_session_closures WHERE task_id=?", (task_id,))


def assert_session_open(db, task_id):
    closure = session_closure(db, task_id)
    if closure and closure["state"] != "failed":
        raise DomainError(
            "TASK_SESSION_CLOSED" if closure["state"] == "closed" else "TASK_SESSION_CLOSING", 409
        )


class TaskSessions:
    def __init__(self, database, executor, confirm):
        self.db, self.executor, self.confirm = database, executor, confirm

    async def close(self, owner, task_id, revision, run_id):
        def reserve(db):
            task = row(db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (task_id, owner))
            if not task:
                raise DomainError("TASK_NOT_FOUND", 404)
            if task["revision"] != revision:
                raise DomainError("TASK_REVISION_CHANGED", 409)
            run = row(
                db,
                "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
                (task_id, revision),
            )
            if not run or run["id"] != run_id:
                raise DomainError("TASK_REVISION_CHANGED", 409)
            prior = session_closure(db, task_id)
            if prior and prior["state"] == "closed":
                return task, run, True
            if prior and prior["state"] in {"closing", "unknown"}:
                raise DomainError("TASK_SESSION_CLOSING", 409)
            if task["state"] not in STABLE or not run["finished_ms"]:
                raise DomainError("TASK_SESSION_BUSY", 409)
            if run["executor_kind"] != "cli" or not run["session_id"] or not self.executor:
                raise DomainError("TASK_SESSION_UNAVAILABLE", 409)
            evidence = json.loads(run["result_json"]) if run["result_json"] else {}
            if (
                run["state"] == "unknown"
                or evidence.get("outcomeKnown") is False
                or evidence.get("inputStopped") is False
            ):
                raise DomainError("TASK_OUTCOME_UNRESOLVED", 409)
            if row(
                db,
                "SELECT id FROM jobs WHERE aggregate_id=? AND kind='task.steer' AND state='queued'",
                (task_id,),
            ):
                raise DomainError("TASK_STEER_PENDING", 409)
            db.execute(
                "INSERT INTO task_session_closures(task_id,task_revision,run_id,launch_id,session_id,state,updated_ms) VALUES(?,?,?,?,?,'closing',?) "
                "ON CONFLICT(task_id) DO UPDATE SET task_revision=excluded.task_revision,run_id=excluded.run_id,launch_id=excluded.launch_id,session_id=excluded.session_id,state='closing',error_code=NULL,updated_ms=excluded.updated_ms",
                (task_id, revision, run_id, run["launch_id"], run["session_id"], now_ms()),
            )
            return task, run, False

        task, run, closed = await self.db.call(reserve, write=True)
        if closed:
            return {"taskId": task_id, "state": "closed"}
        try:
            result = await self.executor.command("close", "--key", run["launch_id"])
            if result.get("state") != "closed" or result.get("session") != run["session_id"]:
                raise DomainError("TASK_SESSION_CLOSE_UNKNOWN", 409)
        except (DomainError, OSError, TimeoutError) as exc:
            code = exc.code if isinstance(exc, DomainError) else "TASK_SESSION_CLOSE_UNKNOWN"
            known = code in {
                "SESSION_NOT_IDLE",
                "SESSION_BINDING_CONFLICT",
                "SESSION_LIFECYCLE_UNAVAILABLE",
                "SESSION_TARGET_NOT_FOUND",
            }
            await self.db.call(
                lambda db: db.execute(
                    "UPDATE task_session_closures SET state=?,error_code=?,updated_ms=? WHERE task_id=?",
                    ("failed" if known else "unknown", code, now_ms(), task_id),
                ),
                write=True,
            )
            raise DomainError(code, 409) from exc

        def finish(db):
            db.execute(
                "UPDATE task_session_closures SET state='closed',updated_ms=? WHERE task_id=?",
                (now_ms(), task_id),
            )
            event(
                db,
                task["origin_conversation_id"],
                "task.session_closed",
                {"taskId": task_id, "sessionId": run["session_id"]},
                task_id=task_id,
            )

        await self.db.call(finish, write=True)
        if task["state"] == "waiting_user":
            await self.confirm(owner, task_id, True, revision=revision, run_id=run_id)
        return {"taskId": task_id, "state": "closed"}
