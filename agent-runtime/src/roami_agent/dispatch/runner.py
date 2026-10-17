"""Task preparation, inherited budgets, verification and recovery."""

import asyncio
import json

import httpx

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import event, row, rows


class TaskDispatcher:
    def __init__(self, database, tasks, executor, verifier, native_executor, wakeup, active):
        self.db, self.tasks, self.executor, self.verifier = database, tasks, executor, verifier
        self.native_executor, self.wakeup, self.active = native_executor, wakeup, active

    async def charge_budget(self, task_id):
        def write(db):
            task = row(db, "SELECT * FROM tasks WHERE id=?", (task_id,))
            current = task
            while current:
                budget = json.loads(current["budget_json"])
                budget["usedSteps"] = budget.get("usedSteps", 0) + 1
                if budget["usedSteps"] > budget["maxTurns"] or now_ms() >= budget["deadlineMs"]:
                    raise DomainError("TASK_BUDGET_EXCEEDED")
                if current["state"] == "cancelling":
                    raise DomainError("TASK_CANCELLING")
                db.execute(
                    "UPDATE tasks SET budget_json=? WHERE id=?", (encoded(budget), current["id"])
                )
                current = (
                    row(db, "SELECT * FROM tasks WHERE id=?", (current["parent_task_id"],))
                    if current["parent_task_id"]
                    else None
                )

        await self.db.call(write, write=True)

    async def run(self, job):
        def start(db):
            task = row(db, "SELECT * FROM tasks WHERE id=?", (job["aggregate_id"],))
            run = row(
                db,
                "SELECT * FROM task_attempts WHERE id=?",
                (json.loads(job["payload_json"])["runId"],),
            )
            if task["state"] != "queued" or run["state"] != "accepted":
                db.execute("UPDATE jobs SET state='done' WHERE id=?", (job["id"],))
                return None
            db.execute(
                "UPDATE jobs SET state='running',attempts=attempts+1 WHERE id=?", (job["id"],)
            )
            preparing = (
                run["executor_kind"] == "cli" and getattr(self.executor, "can_reconcile", False)
            ) or (
                run["executor_kind"] == "native"
                and getattr(self.native_executor, "requires_workspace", lambda task: False)(task)
            )
            db.execute(
                "UPDATE tasks SET state=?,updated_ms=? WHERE id=?",
                ("preparing" if preparing else "running", now_ms(), task["id"]),
            )
            db.execute(
                "UPDATE task_attempts SET state=?,started_ms=? WHERE id=?",
                ("starting" if preparing else "running", now_ms(), run["id"]),
            )
            turn = None
            if run["executor_kind"] == "native":
                b = row(db, "SELECT * FROM branches WHERE id=?", (run["native_branch_id"],))
                tid = identity()
                db.execute(
                    "INSERT INTO turns(id,conversation_id,branch_id,trigger_kind,state,created_ms) VALUES(?,?,?,'user','running',?)",
                    (tid, b["conversation_id"], b["id"], now_ms()),
                )
                db.execute(
                    "UPDATE messages SET turn_id=? WHERE branch_id=? AND turn_id IS NULL",
                    (tid, b["id"]),
                )
                turn = dict(
                    row(db, "SELECT * FROM turns WHERE id=?", (tid,)), owner_id=task["owner_id"]
                )
            event(
                db,
                task["origin_conversation_id"],
                "task.preparing" if preparing else "task.started",
                {"taskId": task["id"], "runId": run["id"]},
                task_id=task["id"],
            )
            return task, run, turn

        started = await self.db.call(start, write=True)
        if not started:
            return
        task, run, turn = started
        try:
            forgotten = await self.db.call(
                lambda db: row(
                    db,
                    "SELECT 1 FROM context_omissions WHERE owner_id=? AND message_id=?",
                    (task["owner_id"], task["origin_message_id"]),
                )
            )
            if forgotten:
                if turn:
                    await self.db.call(
                        lambda db: db.execute(
                            "UPDATE turns SET state='failed',finished_ms=? WHERE id=?",
                            (now_ms(), turn["id"]),
                        ),
                        write=True,
                    )
                raise DomainError("TASK_SOURCE_FORGOTTEN")
            if turn:
                result = await self.native_executor.run(task, run, turn=turn)
            elif self.executor:
                await self.charge_budget(task["id"])
                result = await self.executor.run(task, run)
                if result is None:  # External TUI is alive; report arrives via the CLI callback.
                    return
            else:
                raise DomainError("EXTERNAL_EXECUTOR_NOT_CONFIGURED")
        except asyncio.CancelledError:
            if run["executor_kind"] == "cli" and getattr(self.executor, "can_reconcile", False):
                # The Go runner outlives Python; restart observes the same launch key.
                raise
            await self.end_prepared_turn(turn, "interrupted", "TURN_INTERRUPTED")
            current = await self.db.call(
                lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],))
            )
            uncertain = (
                await self.db.call(
                    lambda db: row(
                        db,
                        "SELECT id FROM tool_calls WHERE turn_id=? AND effect='write' AND state IN ('planned','running','unknown') LIMIT 1",
                        (turn["id"],),
                    )
                )
                if turn
                else None
            )
            if uncertain:
                await self.complete(
                    task,
                    run,
                    {
                        "state": "failed",
                        "summary": "TOOL_STOP_UNCONFIRMED",
                        "outcomeKnown": False,
                        "retryable": False,
                    },
                    "interrupted",
                    unknown=True,
                )
            elif current["state"] == "cancelling":
                await self.tasks.report(
                    task["owner_id"],
                    task["id"],
                    run["id"],
                    task["revision"],
                    {"state": "cancelled", "summary": "Cancelled"},
                )
            else:
                await self.db.call(
                    lambda db: db.execute(
                        "UPDATE tasks SET state='interrupted' WHERE id=?", (task["id"],)
                    ),
                    write=True,
                )
            raise
        except (DomainError, OSError, ValueError, httpx.HTTPError, TimeoutError) as exc:
            await self.end_prepared_turn(
                turn, "failed", exc.code if isinstance(exc, DomainError) else "EXECUTION_FAILED"
            )
            result = {
                "state": "failed",
                "summary": exc.code if isinstance(exc, DomainError) else "EXECUTION_FAILED",
            }
            if result["summary"] in {
                "NATIVE_WORKSPACE_OUTCOME_UNKNOWN",
                "NATIVE_WORKSPACE_RELEASE_UNKNOWN",
                "TOOL_OUTCOME_UNKNOWN",
                "MCP_OUTCOME_UNKNOWN",
            }:
                result.update(outcomeKnown=False, retryable=False)
                await self.complete(task, run, result, "interrupted", unknown=True)
                return
        await self.tasks.report(task["owner_id"], task["id"], run["id"], task["revision"], result)

    async def end_prepared_turn(self, turn, state, code):
        if turn is None:
            return

        def write(db):
            changed = db.execute(
                "UPDATE turns SET state=?,finished_ms=? WHERE id=? AND state='running'",
                (state, now_ms(), turn["id"]),
            )
            if changed.rowcount:
                event(
                    db,
                    turn["conversation_id"],
                    "turn." + state,
                    {"turnId": turn["id"], "error": code},
                    turn_id=turn["id"],
                )

        await self.db.call(write, write=True)

    async def verify(self, job):
        task = await self.db.call(
            lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (job["aggregate_id"],))
        )
        run = await self.db.call(
            lambda db: row(
                db,
                "SELECT * FROM task_attempts WHERE id=?",
                (json.loads(job["payload_json"])["runId"],),
            )
        )
        if not task or task["revision"] != run["task_revision"]:
            await self.db.call(
                lambda db: db.execute("UPDATE jobs SET state='done' WHERE id=?", (job["id"],)),
                write=True,
            )
            return
        children = await self.db.call(
            lambda db: rows(db, "SELECT * FROM tasks WHERE parent_task_id=?", (task["id"],))
        )
        if any(
            c["state"] not in {"succeeded", "failed", "cancelled", "interrupted"} for c in children
        ):
            await self.db.call(
                lambda db: db.execute(
                    "UPDATE jobs SET available_ms=? WHERE id=?", (now_ms() + 100, job["id"])
                ),
                write=True,
            )
            return
        result = json.loads(run["result_json"])
        if children:
            result["children"] = [
                {
                    "taskId": c["id"],
                    "state": c["state"],
                    "goal": json.loads(c["intent_json"])["goal"],
                    "result": await self.db.call(
                        lambda db, c=c: row(
                            db,
                            "SELECT result_json FROM task_attempts WHERE task_id=? ORDER BY attempt_no DESC LIMIT 1",
                            (c["id"],),
                        )
                    ),
                }
                for c in children
            ]
            if (
                task["state"] != "cancelling"
                and result["state"] != "cancelled"
                and any(c["state"] != "succeeded" for c in children)
            ):
                result["state"] = "failed"
        verified = False
        if result["state"] == "succeeded" and task["state"] != "cancelling":
            if self.verifier:
                verified = await self.verifier(task, result)
            else:
                # Native read-only answers can finish; writes require explicit acceptance.
                writes = await self.db.call(
                    lambda db: row(
                        db,
                        "SELECT x.id FROM tool_calls x JOIN turns t ON t.id=x.turn_id WHERE t.branch_id=? AND x.effect='write' AND x.tool_name!='delegate' LIMIT 1",
                        (run["native_branch_id"],),
                    )
                )
                verified = (
                    run["executor_kind"] == "native"
                    and not writes
                    and bool(result.get("summary", "").strip())
                )
        state = (
            result["state"]
            if result["state"] != "succeeded"
            else "succeeded"
            if verified
            else "waiting_user"
        )
        await self.complete(task, run, result, state, job_id=job["id"])

    async def complete(self, task, run, result, state, *, job_id=None, unknown=False):
        def write(db, result=result, state=state):
            current = row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],))
            if current["revision"] != run["task_revision"] or current["state"] in {
                "cancelled",
                "interrupted",
            }:
                if job_id:
                    db.execute("UPDATE jobs SET state='done' WHERE id=?", (job_id,))
                return
            if unknown:
                attempt = row(db, "SELECT result_json FROM task_attempts WHERE id=?", (run["id"],))
                if (
                    current["state"] not in {"preparing", "running", "cancelling"}
                    or attempt["result_json"] is not None
                ):
                    return
                db.execute(
                    "UPDATE task_attempts SET state='unknown',result_json=? WHERE id=? AND task_revision=?",
                    (encoded(result), run["id"], run["task_revision"]),
                )
            elif current["state"] == "cancelling":
                children = rows(db, "SELECT state FROM tasks WHERE parent_task_id=?", (task["id"],))
                if any(
                    c["state"] not in {"succeeded", "failed", "cancelled", "interrupted"}
                    for c in children
                ):
                    if job_id:
                        db.execute(
                            "UPDATE jobs SET available_ms=? WHERE id=?", (now_ms() + 100, job_id)
                        )
                    return
                uncertain = (
                    any(c["state"] == "interrupted" for c in children)
                    or result.get("outcomeKnown") is False
                    or result.get("inputStopped") is False
                )
                state = "interrupted" if uncertain else "cancelled"
                result = {
                    **result,
                    "cancellationRequested": True,
                    "inputStopped": not uncertain,
                }
                if uncertain:
                    result.update(outcomeKnown=False, retryable=False)
            completion = {"taskId": task["id"], "state": state, "result": result}
            db.execute(
                "UPDATE tasks SET state=?,updated_ms=? WHERE id=?", (state, now_ms(), task["id"])
            )
            key = "task.completion:" + run["id"] + ":" + state
            if task["parent_task_id"]:
                event(
                    db,
                    task["origin_conversation_id"],
                    "task." + state,
                    completion,
                    task_id=task["id"],
                )
                if job_id:
                    db.execute("UPDATE jobs SET state='done' WHERE id=?", (job_id,))
                return
            if not row(db, "SELECT id FROM jobs WHERE dedupe_key=?", (key,)):
                tid = identity()
                db.execute(
                    "INSERT INTO turns(id,conversation_id,branch_id,trigger_kind,state,created_ms) VALUES(?,?,?,'completion','queued',?)",
                    (tid, task["origin_conversation_id"], task["origin_branch_id"], now_ms()),
                )
                db.execute(
                    "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) VALUES(?,'turn.run',?,?,?,'queued',?)",
                    (identity(), tid, key, encoded({"completion": completion}), now_ms()),
                )
                event(
                    db,
                    task["origin_conversation_id"],
                    "task." + state,
                    completion,
                    task_id=task["id"],
                )
            if job_id:
                db.execute("UPDATE jobs SET state='done' WHERE id=?", (job_id,))

        await self.db.call(write, write=True)

    async def confirm(self, owner, task_id, accepted):
        task = await self.db.call(
            lambda db: row(db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (task_id, owner))
        )
        if not task:
            raise DomainError("TASK_NOT_FOUND", 404)
        if task["state"] != "waiting_user":
            raise DomainError("TASK_NOT_WAITING_VERIFICATION", 409)
        run = await self.db.call(
            lambda db: row(
                db,
                "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
                (task_id, task["revision"]),
            )
        )
        await self.complete(
            task, run, json.loads(run["result_json"]), "succeeded" if accepted else "failed"
        )
        self.wakeup.set()
        return {"taskId": task_id, "state": "succeeded" if accepted else "failed"}

    async def cancel(self):
        cancelling = await self.db.call(
            lambda db: rows(db, "SELECT * FROM tasks WHERE state='cancelling'")
        )
        for task in cancelling:
            active = next((a for a in self.active.values() if a["task"] == task["id"]), None)
            if active and getattr(self.executor, "can_reconcile", False):
                attempt = await self.db.call(
                    lambda db, task=task: row(
                        db,
                        "SELECT executor_kind FROM task_attempts WHERE task_id=? ORDER BY attempt_no DESC LIMIT 1",
                        (task["id"],),
                    )
                )
                if attempt and attempt["executor_kind"] == "cli":
                    continue
            if active:
                if not active["handle"].cancelling():
                    active["handle"].cancel()
            else:
                run = await self.db.call(
                    lambda db, task=task: row(
                        db,
                        "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
                        (task["id"], task["revision"]),
                    )
                )
                if run["state"] == "accepted":
                    await self.tasks.report(
                        task["owner_id"],
                        task["id"],
                        run["id"],
                        task["revision"],
                        {"state": "cancelled", "summary": "Cancelled before start"},
                    )
                elif (
                    run["executor_kind"] == "cli"
                    and self.executor
                    and not getattr(self.executor, "can_reconcile", False)
                ):
                    await self.executor.cancel(task, run)

    async def recover(self):
        def write(db):
            for task in rows(db, "SELECT * FROM tasks WHERE state IN ('preparing','running')"):
                external = row(
                    db,
                    "SELECT id FROM task_attempts WHERE task_id=? AND task_revision=? AND executor_kind='cli' AND result_json IS NULL",
                    (task["id"], task["revision"]),
                )
                if external and getattr(self.executor, "can_reconcile", False):
                    db.execute(
                        "UPDATE task_attempts SET state='unknown' WHERE id=?", (external["id"],)
                    )
                    db.execute(
                        "UPDATE jobs SET state='done' WHERE kind='task.run' AND aggregate_id=?",
                        (task["id"],),
                    )
                    continue
                db.execute(
                    "UPDATE task_attempts SET state='unknown' WHERE task_id=? AND state IN ('starting','running')",
                    (task["id"],),
                )
                db.execute("UPDATE tasks SET state='interrupted' WHERE id=?", (task["id"],))
                db.execute(
                    "UPDATE jobs SET state='failed' WHERE kind='task.run' AND aggregate_id=?",
                    (task["id"],),
                )
                event(
                    db,
                    task["origin_conversation_id"],
                    "task.interrupted",
                    {"taskId": task["id"], "reason": "runtime_restart"},
                    task_id=task["id"],
                )

        await self.db.call(write, write=True)
