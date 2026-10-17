"Thin local CLI adapter; Go owns sessions, process supervision and launch receipts."

import json
import math
from pathlib import Path

from roami_agent.executors.project import provision_project
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import event, row, rows
from roami_agent.tools.process import execute


class CodingExecutor:
    can_reconcile = True

    def __init__(self, database, settings):
        self.db, self.settings = database, settings

    async def command(self, sub, *args, spec=None):
        response = await execute(
            [self.settings.cli_bin, "agent", "execution", sub, *args],
            timeout=180 if spec and spec.get("projectId") else 15,
            input_data=encoded(spec).encode() if spec is not None else None,
        )
        if response["exitCode"]:
            # CLI diagnostics may contain paths or account details; keep them out of model context.
            raise DomainError("CODING_EXECUTOR_UNAVAILABLE", 503)
        try:
            value = json.loads(response["stdout"])
        except (ValueError, TypeError) as exc:
            raise DomainError("INVALID_EXECUTOR_RECEIPT") from exc
        if not isinstance(value, dict) or (
            value.get("session") is not None and not isinstance(value["session"], str)
        ):
            raise DomainError("INVALID_EXECUTOR_RECEIPT")
        return value

    async def run(self, task, run):
        spec = json.loads(task["intent_json"])
        target = spec["target"]
        if target["kind"] == "new_project":
            target = await provision_project(self.settings, task, run)
        if target["kind"] not in {"new_session", "project"}:
            raise DomainError("CODING_TARGET_ADAPTER_NOT_IMPLEMENTED")
        if spec.get("fromMessageId"):
            raise DomainError("CODING_CHECKPOINT_FORK_NOT_IMPLEMENTED")
        if json.loads(task["budget_json"])["deadlineMs"] <= now_ms():
            raise DomainError("TASK_BUDGET_EXCEEDED")
        launch = {
            "key": run["launch_id"],
            "executor": spec["executor"],
            "prompt": spec["goal"],
            "timeoutSeconds": max(
                1, math.ceil((json.loads(task["budget_json"])["deadlineMs"] - now_ms()) / 1000)
            ),
        }
        if target["kind"] == "project":
            if not isinstance(target.get("projectId"), str) or not target["projectId"]:
                raise DomainError("CODING_PROJECT_ID_REQUIRED")
            if target.get("directory"):
                raise DomainError("CODING_PROJECT_WORKSPACE_OVERRIDE_UNSUPPORTED")
            launch.update(
                projectId=target["projectId"],
                base=target.get("base", ""),
                remote=target.get("remote", ""),
            )
            if "workspaceId" in target:
                if not isinstance(target["workspaceId"], str) or not target["workspaceId"]:
                    raise DomainError("CODING_WORKSPACE_ID_REQUIRED")
                if target.get("base") or target.get("remote"):
                    raise DomainError("CODING_WORKSPACE_REUSE_CONFLICT")
                launch["workspaceId"] = target["workspaceId"]
        else:
            directory = target.get("directory") or self.settings.coding_directory
            if not isinstance(directory, (str, Path)) or not Path(directory).is_absolute():
                raise DomainError("CODING_DIRECTORY_REQUIRED")
            launch["directory"] = str(Path(directory).resolve())
        try:
            receipt = await self.command(
                "launch",
                "--file",
                "-",
                spec=launch,
            )
        except (DomainError, OSError, TimeoutError):
            await self.record(task, run, {"state": "unknown"})
            return None
        await self.record(task, run, receipt)
        return self.result(receipt)

    async def record(self, task, run, receipt):
        state = {"running": "running", "cancelling": "stopping"}.get(receipt.get("state"))
        if receipt.get("result") is None and state is None:
            state = "unknown"

        def write(db):
            current = row(db, "SELECT * FROM task_attempts WHERE id=?", (run["id"],))
            if not current or current["result_json"]:
                return
            if receipt.get("workspace"):
                workspace_key = "workspace:" + run["id"]
                existing = row(
                    db, "SELECT payload_json FROM events WHERE event_key=?", (workspace_key,)
                )
                workspace = {
                    "taskId": task["id"],
                    "runId": run["id"],
                    "workspace": receipt["workspace"],
                }
                if existing and json.loads(existing["payload_json"]) != workspace:
                    raise DomainError("WORKSPACE_BINDING_CONFLICT", 409)
                if not existing:
                    event(
                        db,
                        task["origin_conversation_id"],
                        "task.workspace_prepared",
                        workspace,
                        task_id=task["id"],
                        key=workspace_key,
                    )
            if receipt.get("workspace"):
                db.execute(
                    "UPDATE tasks SET target_json=? WHERE id=? AND revision=?",
                    (
                        encoded(
                            {
                                "nodeId": "local",
                                "projectId": receipt["workspace"].get("projectId"),
                                "workspaceId": receipt["workspace"].get("workspaceId"),
                                "workdir": receipt["workspace"].get("directory"),
                                "sessionId": receipt.get("session"),
                                "workspace": receipt["workspace"],
                            }
                        ),
                        task["id"],
                        run["task_revision"],
                    ),
                )
            if state == "running" and receipt.get("session"):
                was_preparing = row(
                    db,
                    "SELECT id FROM tasks WHERE id=? AND state='preparing' AND revision=?",
                    (task["id"], run["task_revision"]),
                )
                if was_preparing:
                    db.execute(
                        "UPDATE tasks SET state='running',updated_ms=? WHERE id=?",
                        (now_ms(), task["id"]),
                    )
                    event(
                        db,
                        task["origin_conversation_id"],
                        "task.started",
                        {"taskId": task["id"], "runId": run["id"]},
                        task_id=task["id"],
                    )
            db.execute(
                "UPDATE task_attempts SET session_id=COALESCE(?,session_id),state=? WHERE id=?",
                (receipt.get("session"), state or current["state"], run["id"]),
            )
            if state == "unknown" and not row(
                db, "SELECT id FROM events WHERE event_key=?", ("observation-unknown:" + run["id"],)
            ):
                event(
                    db,
                    task["origin_conversation_id"],
                    "task.observation_unknown",
                    {"taskId": task["id"], "runId": run["id"]},
                    task_id=task["id"],
                    key="observation-unknown:" + run["id"],
                )

        await self.db.call(write, write=True)

    @staticmethod
    def result(receipt):
        if receipt.get("state") == "not_started":
            return {"state": "failed", "summary": "CODING_EXECUTOR_NOT_STARTED"}
        result = receipt.get("result")
        if result is None:
            return None
        if not isinstance(result, dict) or result.get("state") not in {
            "succeeded",
            "failed",
            "cancelled",
        }:
            raise DomainError("INVALID_EXECUTOR_RESULT")
        return {
            **result,
            "sessionId": receipt.get("session"),
            "workspace": receipt.get("workspace"),
            "executor": "roami-cli",
        }

    async def poll(self, tasks):
        pending = await self.db.call(
            lambda db: rows(
                db,
                "SELECT a.*,t.owner_id FROM task_attempts a JOIN tasks t ON t.id=a.task_id "
                "WHERE a.executor_kind='cli' AND a.result_json IS NULL "
                "AND a.task_revision=t.revision AND t.state IN ('preparing','running','cancelling') "
                "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.kind='task.run' AND j.aggregate_id=t.id AND j.state IN ('queued','running')) "
                "ORDER BY a.started_ms LIMIT 100",
            )
        )
        for run in pending:
            task = await self.db.call(
                lambda db, run=run: row(db, "SELECT * FROM tasks WHERE id=?", (run["task_id"],))
            )
            try:
                if task["state"] == "cancelling":
                    await self.cancel(task, run)
                receipt = await self.command("status", "--key", run["launch_id"])
                await self.record(task, run, receipt)
                result = self.result(receipt)
                if result is not None:
                    await tasks.report(
                        run["owner_id"], run["task_id"], run["id"], run["task_revision"], result
                    )
            except (DomainError, OSError, TimeoutError):
                # A failed observation is neither a terminal report nor permission to relaunch.
                await self.record(task, run, {"state": "unknown"})

    async def cancel(self, task, run):
        try:
            receipt = await self.command("cancel", "--key", run["launch_id"])
            await self.record(task, run, receipt)
        except (DomainError, OSError, TimeoutError):
            await self.record(task, run, {"state": "unknown"})
