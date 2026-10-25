"""Native task bindings confined to the outer evaluation container's owned workspace."""

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from roami_agent.improvement.contracts import require
from roami_agent.protocol.errors import DomainError

NATIVE_TASK_REQUEST = "本次任务明确使用内置Native Worker执行。"


def bind_evaluation_tasks(runtime, workspace):
    root = workspace.resolve()

    @asynccontextmanager
    async def prepared(settings, task, run, *, stopped=None):
        target = json.loads(task["intent_json"])["target"]
        require(
            target["kind"] == "new_session"
            and target.get("nodeId", "local") == "local"
            and not target.get("resourceOnly")
            and bool(target.get("directory"))
            and Path(target["directory"]).resolve() == root,
            "RSI_TASK_WORKSPACE_REQUIRED",
        )
        try:
            # The outer Docker lifetime owns this directory; no Go/tmux lease is created.
            yield {"workspaceId": "rsi-" + run["id"], "directory": str(root), "projectId": None}
        finally:
            if stopped is not None:
                require(await stopped(), "RSI_TASK_WRITE_UNKNOWN")

    runtime.dispatch.native_executor.workspace_factory = prepared


async def settle_evaluation_tasks(database):
    while True:
        states = await database.call(
            lambda db: [r[0] for r in db.execute("SELECT state FROM tasks")]
        )
        if any(s in {"failed", "cancelled", "interrupted"} for s in states):
            raise DomainError("RSI_NATIVE_TASK_FAILED")
        active = await database.call(
            lambda db: db.execute(
                "SELECT COUNT(*) FROM jobs WHERE kind IN ('turn.run','task.run','task.verify') AND state IN ('queued','running')"
            ).fetchone()[0]
        )
        if not active and all(s in {"succeeded", "waiting_user"} for s in states):
            return
        await asyncio.sleep(0.01)
