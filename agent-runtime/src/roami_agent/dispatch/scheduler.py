"""Durable job scheduling with separate Main and Worker capacity."""

import asyncio
import json
import logging

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.storage.database import rows

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(
        self,
        database,
        settings,
        context,
        dispatch,
        mailbox,
        run_turn,
        wakeup,
        active,
        memory_jobs,
        *,
        task_sessions=None,
    ):
        self.db, self.settings, self.context, self.dispatch = database, settings, context, dispatch
        self.mailbox, self.run_turn, self.wakeup, self.active = mailbox, run_turn, wakeup, active
        self.active_branches = set()
        self.stopping = False
        self.memory_jobs = memory_jobs
        self.task_sessions = task_sessions

    async def run(self):
        while not self.stopping:
            self.wakeup.clear()
            try:
                await self._scan()
                await self.dispatch.cancel()
                await self.memory_jobs.scan()
            except (DomainError, OSError):
                log.exception("Agent supervisor iteration failed")
            try:
                await asyncio.wait_for(self.wakeup.wait(), timeout=0.1)
            except TimeoutError:
                pass

    async def _scan(self):
        await self.dispatch.tasks.revisions.advance()
        queued = await self.db.call(
            lambda db: rows(
                db,
                "SELECT j.*,t.branch_id,b.id AS native_branch_id,a.executor_kind FROM jobs j "
                "LEFT JOIN turns t ON j.kind='turn.run' AND t.id=j.aggregate_id "
                "LEFT JOIN task_attempts a ON j.kind='task.run' AND a.id=json_extract(j.payload_json,'$.runId') "
                "LEFT JOIN branches b ON b.id=a.native_branch_id "
                "WHERE j.state='queued' AND j.kind IN ('turn.run','context.compact','task.run','task.verify','task.close_session','memory.daily','memory.extract') "
                "AND j.available_ms<=? ORDER BY CASE j.kind WHEN 'task.verify' THEN 0 WHEN 'task.close_session' THEN 1 WHEN 'turn.run' THEN 2 WHEN 'task.run' THEN 3 WHEN 'context.compact' THEN 4 WHEN 'memory.daily' THEN 5 ELSE 6 END,"
                "CASE WHEN j.kind='turn.run' AND t.trigger_kind='user' AND COALESCE(json_extract(j.payload_json,'$.deferred'),0)=0 THEN 0 ELSE 1 END,j.rowid LIMIT 100",
                (now_ms(),),
            )
        )
        external_running = await self.db.call(
            lambda db: db.execute(
                "SELECT COUNT(*) FROM tasks t JOIN task_attempts a ON a.task_id=t.id AND a.task_revision=t.revision "
                "WHERE a.executor_kind='cli' AND t.state IN ('preparing','running','cancelling')"
            ).fetchone()[0]
        )
        for job in queued:
            if getattr(self.settings, "updating", False):
                return
            if job["id"] in self.active:
                continue
            memory_job = job["kind"].startswith("memory.")
            if memory_job and any(item.get("memory") for item in self.active.values()):
                continue
            group = (
                "control"
                if job["kind"] == "task.close_session"
                else "main"
                if job["kind"] == "turn.run"
                else "worker"
            )
            capacity = (
                1
                if group == "control"
                else self.settings.main_concurrency
                if group == "main"
                else self.settings.workers
            )
            if sum(v["group"] == group for v in self.active.values()) >= capacity:
                continue
            if job.get("executor_kind") == "cli":
                if external_running >= self.settings.workers:
                    continue
                external_running += 1
            branch = job.get("branch_id") or job.get("native_branch_id")
            if job["kind"] == "context.compact":
                branch = json.loads(job["payload_json"])["branchId"]
            if branch and branch in self.active_branches:
                continue
            if branch:
                self.active_branches.add(branch)
            handle = asyncio.create_task(self._job(job), name="agent-job-" + job["id"])
            self.active[job["id"]] = {
                "handle": handle,
                "group": group,
                "branch": branch,
                "task": job["aggregate_id"] if job["kind"] in {"task.run", "task.verify"} else None,
                "kind": job["kind"],
                "memory": memory_job,
            }
            handle.add_done_callback(lambda _, key=job["id"]: self._finished(key))

    def _finished(self, key):
        item = self.active.pop(key, None)
        if item and item["branch"]:
            self.active_branches.discard(item["branch"])
        self.wakeup.set()

    async def _job(self, job):
        try:
            if job["kind"] == "task.close_session":
                await self.task_sessions.advance(job)
                return
            if job["kind"].startswith("memory."):
                await self.memory_jobs.run(job)
                return
            if job["kind"] == "context.compact":
                await self.context.run(job["id"])
                return
            if job["kind"] == "turn.run":
                turn = await self.mailbox.claim(job)
                if turn:
                    await self.run_turn(
                        turn, "main", completion=json.loads(job["payload_json"]).get("completion")
                    )
            elif job["kind"] == "task.run":
                await self.dispatch.run(job)
            elif job["kind"] == "task.verify":
                await self.dispatch.verify(job)
            await self.db.call(
                lambda db: db.execute(
                    "UPDATE jobs SET state='done' WHERE id=? AND state='running'", (job["id"],)
                ),
                write=True,
            )
        except asyncio.CancelledError:
            await self.db.call(
                lambda db: db.execute(
                    "UPDATE jobs SET state='failed' WHERE id=? AND state='running'", (job["id"],)
                ),
                write=True,
            )
            raise
        except Exception:
            # Every admitted job must have a durable terminal outcome, including programming failures.
            log.exception("Agent job failed: %s", job["id"])
            await self.db.call(
                lambda db: db.execute("UPDATE jobs SET state='failed' WHERE id=?", (job["id"],)),
                write=True,
            )
