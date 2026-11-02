"""Explicit user closure, fenced against concurrent task continuation."""

import json

from roami_agent.conversation.activity_events import activity_event as event
from roami_agent.dispatch.task_cancellation import request_task_cancellation
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row, rows

STABLE = {"succeeded", "failed", "cancelled", "interrupted", "waiting_user"}


def session_closure(db, task_id):
    return row(db, "SELECT * FROM task_session_closures WHERE task_id=?", (task_id,))


def assert_session_open(db, task_id):
    closure = row(
        db,
        "WITH RECURSIVE parents(id,parent_task_id) AS (SELECT id,parent_task_id FROM tasks WHERE id=? UNION SELECT t.id,t.parent_task_id FROM tasks t JOIN parents p ON t.id=p.parent_task_id) SELECT c.* FROM task_session_closures c JOIN parents p ON p.id=c.task_id WHERE c.state!='failed' LIMIT 1",
        (task_id,),
    )
    if closure and closure["state"] != "failed":
        raise DomainError(
            "TASK_SESSION_CLOSED" if closure["state"] == "closed" else "TASK_SESSION_CLOSING", 409
        )


class TaskSessions:
    def __init__(self, database, executor, confirm, *, cleanup=None):
        self.db, self.executor, self.confirm = database, executor, confirm
        self.cleanup = cleanup

    async def request(self, owner, task_id, revision, run_id):
        def reserve(db):
            task = row(db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (task_id, owner))
            if not task:
                raise DomainError("TASK_NOT_FOUND", 404)
            run = row(
                db,
                "SELECT * FROM task_attempts WHERE task_id=? ORDER BY attempt_no DESC LIMIT 1",
                (task_id,),
            )
            if task["revision"] != revision or not run or run["id"] != run_id:
                raise DomainError("TASK_REVISION_CHANGED", 409)
            prior = session_closure(db, task_id)
            if prior and prior["state"] in {"closing", "closed"}:
                return {"taskId": task_id, "state": prior["state"]}
            native = row(db, "SELECT id FROM native_sessions WHERE task_id=?", (task_id,))
            session_id = (
                native["id"] if run["executor_kind"] == "native" and native else run["session_id"]
            )
            if not session_id:
                raise DomainError("TASK_SESSION_UNAVAILABLE", 409)
            db.execute(
                "INSERT INTO task_session_closures(task_id,task_revision,run_id,launch_id,session_id,state,updated_ms) VALUES(?,?,?,?,?,'closing',?) ON CONFLICT(task_id) DO UPDATE SET task_revision=excluded.task_revision,run_id=excluded.run_id,launch_id=excluded.launch_id,session_id=excluded.session_id,state='closing',error_code=NULL,updated_ms=excluded.updated_ms",
                (task_id, revision, run_id, run["launch_id"], session_id, now_ms()),
            )
            tree = "WITH RECURSIVE tree(id) AS (SELECT ? UNION SELECT t.id FROM tasks t JOIN tree ON t.parent_task_id=tree.id) "
            if row(
                db,
                tree
                + "SELECT id FROM tasks WHERE id IN (SELECT id FROM tree) AND state NOT IN ('succeeded','failed','cancelled','interrupted','waiting_user') LIMIT 1",
                (task_id,),
            ):
                request_task_cancellation(db, owner, task_id)
            for job in rows(
                db,
                tree
                + "SELECT * FROM jobs WHERE aggregate_id IN (SELECT id FROM tree) AND kind='task.steer' AND state='queued'",
                (task_id,),
            ):
                payload = json.loads(job["payload_json"])
                payload["status"] = "cancelled"
                db.execute(
                    "UPDATE jobs SET state='done',payload_json=? WHERE id=?",
                    (encoded(payload), job["id"]),
                )
            db.execute(
                "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) VALUES(?,'task.close_session',?,?,?,'queued',?) ON CONFLICT(dedupe_key) DO UPDATE SET state='queued',payload_json=excluded.payload_json,available_ms=excluded.available_ms",
                (
                    identity(),
                    task_id,
                    "close-session:" + task_id,
                    encoded({"owner": owner, "revision": revision, "runId": run_id}),
                    now_ms(),
                ),
            )
            event(
                db,
                task["origin_conversation_id"],
                "task.session_closing",
                {"taskId": task_id},
                task_id=task_id,
            )
            return {"taskId": task_id, "state": "closing"}

        result = await self.db.call(reserve, write=True)
        if result["state"] == "closed":
            return await self.close(owner, task_id, revision, run_id)
        return result

    async def advance(self, job):
        payload = json.loads(job["payload_json"])
        try:
            children = await self.db.call(
                lambda db: rows(
                    db,
                    "WITH RECURSIVE tree(id,depth) AS (SELECT id,1 FROM tasks WHERE parent_task_id=? UNION ALL SELECT t.id,tree.depth+1 FROM tasks t JOIN tree ON t.parent_task_id=tree.id) SELECT t.*,a.id AS run_id FROM tree JOIN tasks t ON t.id=tree.id JOIN task_attempts a ON a.task_id=t.id AND a.attempt_no=(SELECT MAX(z.attempt_no) FROM task_attempts z WHERE z.task_id=t.id) ORDER BY tree.depth DESC",
                    (job["aggregate_id"],),
                )
            )
            for child in children:
                await self.close(
                    payload["owner"], child["id"], child["revision"], child["run_id"], pending=True
                )
            await self.close(
                payload["owner"],
                job["aggregate_id"],
                payload["revision"],
                payload["runId"],
                pending=True,
            )
        except (DomainError, OSError, TimeoutError) as exc:
            code = exc.code if isinstance(exc, DomainError) else "TASK_SESSION_CLOSE_UNKNOWN"
            if code in {"TASK_SESSION_BUSY", "TASK_RESOURCE_NOT_RELEASED", "SESSION_NOT_IDLE"}:
                await self.db.call(
                    lambda db: db.execute(
                        "UPDATE jobs SET state='queued',available_ms=? WHERE id=?",
                        (now_ms() + 1000, job["id"]),
                    ),
                    write=True,
                )
                return
            await self.db.call(
                lambda db: db.execute(
                    "UPDATE task_session_closures SET state='failed',error_code=?,updated_ms=? WHERE task_id=? AND state!='closed'",
                    (code, now_ms(), job["aggregate_id"]),
                ),
                write=True,
            )
            await self.db.call(
                lambda db: db.execute("UPDATE jobs SET state='failed' WHERE id=?", (job["id"],)),
                write=True,
            )
            await self.db.call(
                lambda db: event(
                    db,
                    row(
                        db,
                        "SELECT origin_conversation_id FROM tasks WHERE id=?",
                        (job["aggregate_id"],),
                    )["origin_conversation_id"],
                    "task.session_close_failed",
                    {"taskId": job["aggregate_id"], "errorCode": code},
                    task_id=job["aggregate_id"],
                ),
                write=True,
            )
            return
        await self.db.call(
            lambda db: db.execute("UPDATE jobs SET state='done' WHERE id=?", (job["id"],)),
            write=True,
        )

    async def close(self, owner, task_id, revision, run_id, *, pending=False):
        def finish(db, task, run):
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
            if (
                prior
                and prior["state"] in {"closing", "unknown"}
                and run["executor_kind"] != "native"
                and not pending
            ):
                raise DomainError("TASK_SESSION_CLOSING", 409)
            if task["state"] not in STABLE or not run["finished_ms"]:
                raise DomainError("TASK_SESSION_BUSY", 409)
            tree = "WITH RECURSIVE tree(id) AS (SELECT ? UNION SELECT t.id FROM tasks t JOIN tree ON t.parent_task_id=tree.id) "
            if row(
                db,
                tree
                + "SELECT 1 FROM resources WHERE owner_task_id IN (SELECT id FROM tree) AND (lease_until_ms IS NOT NULL OR state!='idle') LIMIT 1",
                (task_id,),
            ):
                raise DomainError("TASK_RESOURCE_NOT_RELEASED", 409)
            if row(
                db,
                tree
                + "SELECT 1 FROM tasks WHERE id IN (SELECT id FROM tree) AND id!=? AND state NOT IN ('succeeded','failed','cancelled','interrupted') LIMIT 1",
                (task_id, task_id),
            ):
                raise DomainError("TASK_SESSION_BUSY", 409)
            if row(
                db,
                tree
                + "SELECT 1 FROM turns u JOIN task_attempts a ON a.native_branch_id=u.branch_id WHERE a.task_id IN (SELECT id FROM tree) AND u.state IN ('queued','running') UNION ALL SELECT 1 FROM tool_calls x JOIN turns u ON u.id=x.turn_id JOIN task_attempts a ON a.native_branch_id=u.branch_id WHERE a.task_id IN (SELECT id FROM tree) AND x.state IN ('planned','running','unknown') LIMIT 1",
                (task_id,),
            ):
                raise DomainError("TASK_SESSION_BUSY", 409)
            if row(
                db,
                tree
                + "SELECT 1 FROM task_attempts a JOIN tasks c ON c.id=a.task_id WHERE a.task_id IN (SELECT id FROM tree) AND a.task_id!=? AND a.task_revision=c.revision AND a.attempt_no=(SELECT MAX(z.attempt_no) FROM task_attempts z WHERE z.task_id=c.id) AND (a.finished_ms IS NULL OR a.state='unknown' OR json_extract(a.result_json,'$.inputStopped')=0 OR json_extract(a.result_json,'$.outcomeKnown')=0) LIMIT 1",
                (task_id, task_id),
            ):
                raise DomainError("TASK_OUTCOME_UNRESOLVED", 409)
            if run["executor_kind"] == "native":
                native = row(
                    db, "SELECT id,branch_id FROM native_sessions WHERE task_id=?", (task_id,)
                )
                if not native:
                    raise DomainError("TASK_SESSION_UNAVAILABLE", 409)
                run["session_id"] = native["id"]
            elif run["executor_kind"] != "cli" or not run["session_id"] or not self.executor:
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
                tree
                + "SELECT id FROM jobs WHERE aggregate_id IN (SELECT id FROM tree) AND kind='task.steer' AND state='queued'",
                (task_id,),
            ):
                raise DomainError("TASK_STEER_PENDING", 409)
            db.execute(
                "INSERT INTO task_session_closures(task_id,task_revision,run_id,launch_id,session_id,state,updated_ms) VALUES(?,?,?,?,?,'closing',?) "
                "ON CONFLICT(task_id) DO UPDATE SET task_revision=excluded.task_revision,run_id=excluded.run_id,launch_id=excluded.launch_id,session_id=excluded.session_id,state='closing',error_code=NULL,updated_ms=excluded.updated_ms",
                (task_id, revision, run_id, run["launch_id"], run["session_id"], now_ms()),
            )
            if run["executor_kind"] == "native" and not self.cleanup:
                finish(db, task, run)
                return task, run, True
            return task, run, False

        task, run, closed = await self.db.call(reserve, write=True)
        if closed:
            if task["state"] == "waiting_user":
                await self.confirm(owner, task_id, True, revision=revision, run_id=run_id)
            return {"taskId": task_id, "state": "closed"}
        try:
            if run["executor_kind"] == "cli":
                result = await self.executor.command("close", "--key", run["launch_id"])
                if result.get("state") != "closed" or result.get("session") != run["session_id"]:
                    raise DomainError("TASK_SESSION_CLOSE_UNKNOWN", 409)
            if self.cleanup:
                await self.cleanup(task, run)
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
                    (
                        "closing"
                        if pending and code == "SESSION_NOT_IDLE"
                        else "failed"
                        if known
                        else "unknown",
                        code,
                        now_ms(),
                        task_id,
                    ),
                ),
                write=True,
            )
            raise DomainError(code, 409) from exc

        await self.db.call(lambda db: finish(db, task, run), write=True)
        if task["state"] == "waiting_user":
            await self.confirm(owner, task_id, True, revision=revision, run_id=run_id)
        return {"taskId": task_id, "state": "closed"}
