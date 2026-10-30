"""Retain deliverables before asking Go to remove task-owned worktrees."""

import json

from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import rows


class TaskWorkspaceCleanup:
    def __init__(self, database, settings, tasks):
        self.db, self.tasks = database, tasks
        self.executor = CodingExecutor(database, settings)

    async def __call__(self, task, run):
        await self.tasks.get(task["owner_id"], task["id"])
        attempts = await self.db.call(
            lambda db: rows(
                db,
                "SELECT a.* FROM task_attempts a WHERE task_id=? AND (a.session_id IS NOT NULL OR EXISTS(SELECT 1 FROM events e WHERE e.event_key='workspace:'||a.id)) ORDER BY attempt_no DESC",
                (task["id"],),
            )
        )
        for attempt in attempts:
            target = json.loads(task["target_json"] or "{}")
            if attempt["executor_kind"] == "native" and target.get("workspace", {}).get(
                "taskDirectory"
            ):
                continue
            result = await self.executor.command("cleanup", "--key", attempt["launch_id"])
            if result.get("state") != "cleaned":
                raise DomainError("WORKSPACE_CLEANUP_UNAVAILABLE", 409)
