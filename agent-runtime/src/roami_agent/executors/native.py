"""Native branches bind to Go-prepared workspaces before model/tool admission."""

import asyncio
import json

from roami_agent.executors.workspace import hold_workspace
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import event, row


class NativeExecutor:
    def __init__(self, run_turn, database=None, settings=None, workspace_factory=hold_workspace):
        self.run_turn, self.db, self.settings = run_turn, database, settings
        self.workspace_factory = workspace_factory

    def requires_workspace(self, task):
        target = json.loads(task["intent_json"])["target"]
        return (
            target["kind"] != "new_session"
            or target.get("nodeId", "local") != "local"
            or bool(target.get("directory") or getattr(self.settings, "coding_directory", None))
        )

    async def run(self, task, run, *, turn=None):
        if turn is None or turn["branch_id"] != run["native_branch_id"]:
            raise DomainError("NATIVE_EXECUTION_CONTEXT_MISMATCH")

        async def execute(prepared):
            text = await self.run_turn(prepared, "worker", task_id=task["id"])
            return {"state": "succeeded", "summary": text}

        remaining = (json.loads(task["budget_json"])["deadlineMs"] - now_ms()) / 1000
        async with asyncio.timeout(max(0, remaining)):
            if not self.requires_workspace(task):
                return await execute(turn)

            async def stopped():
                pending = await self.db.call(
                    lambda db: row(
                        db,
                        "SELECT id FROM tool_calls WHERE turn_id=? AND effect='write' AND state IN ('planned','running','unknown') LIMIT 1",
                        (turn["id"],),
                    )
                )
                return pending is None

            async with self.workspace_factory(
                self.settings, task, run, stopped=stopped
            ) as workspace:

                def bind(db):
                    assert_context_admitted(db, turn)
                    changed = db.execute(
                        "UPDATE tasks SET state='running',target_json=?,updated_ms=? WHERE id=? AND revision=? AND state IN ('preparing','running')",
                        (
                            encoded(
                                {
                                    "nodeId": "local",
                                    "projectId": workspace.get("projectId"),
                                    "workspaceId": workspace["workspaceId"],
                                    "workdir": workspace["directory"],
                                    "workspace": workspace,
                                }
                            ),
                            now_ms(),
                            task["id"],
                            run["task_revision"],
                        ),
                    )
                    if changed.rowcount != 1:
                        raise DomainError("TASK_CANCELLING")
                    db.execute(
                        "UPDATE task_attempts SET state='running' WHERE id=? AND task_revision=? AND state='starting'",
                        (run["id"], run["task_revision"]),
                    )
                    event(
                        db,
                        task["origin_conversation_id"],
                        "task.workspace_prepared",
                        {"taskId": task["id"], "runId": run["id"], "workspace": workspace},
                        task_id=task["id"],
                        key="workspace:" + run["id"],
                    )
                    event(
                        db,
                        task["origin_conversation_id"],
                        "task.started",
                        {"taskId": task["id"], "runId": run["id"]},
                        task_id=task["id"],
                    )

                await self.db.call(bind, write=True)
                return await execute(dict(turn, workspace=workspace))
