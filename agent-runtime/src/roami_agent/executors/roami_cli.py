"Thin local CLI adapter; Go owns sessions, process supervision and launch receipts."

import json
import math
from pathlib import Path

from roami_agent.context.execution_brief import (
    execution_guide,
    managed_handoff,
    managed_setup,
    swarm_handoff,
)
from roami_agent.conversation.activity_events import activity_event as event
from roami_agent.executors.professional_brief import professional_brief
from roami_agent.executors.project import provision_project
from roami_agent.executors.task_directory import automatic_task_directory, prepare_task_directory
from roami_agent.protocol.errors import DomainError, ToolPreflightError, public_error_code
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row, rows
from roami_agent.storage.swarm_coordination_tasks import prepared_authority
from roami_agent.storage.task_reports import retain_reported_progress
from roami_agent.tools.process import execute

SESSION_REJECTIONS = {
    "SESSION_LIFECYCLE_UNAVAILABLE",
    "SESSION_NOT_IDLE",
    "SESSION_DIRECTORY_CHANGED",
    "SESSION_TARGET_AMBIGUOUS",
    "SESSION_TARGET_NOT_FOUND",
    "SESSION_PANE_AMBIGUOUS",
    "SESSION_PROCESS_OBSERVATION_UNAVAILABLE",
    "INVALID_SESSION_EXECUTION_SPEC",
    "SESSION_RECOVERY_BINDING_CONFLICT",
    "SESSION_RECOVERY_SOURCE_CHANGED",
    "SESSION_RECOVERY_EXPLICITLY_CLOSED",
    "SESSION_RECOVERY_OUTCOME_UNRESOLVED",
    "SESSION_RECOVERY_STOP_UNCONFIRMED",
    "SESSION_RECOVERY_TRANSCRIPT_UNAVAILABLE",
    "SESSION_RECOVERY_WORKSPACE_CHANGED",
    "SESSION_RECOVERY_ALREADY_CLAIMED",
    "SESSION_RECOVERY_TARGET_OBSERVATION_FAILED",
    "SESSION_RECOVERY_HOOKS_UNAVAILABLE",
    "TASK_SESSION_CLOSED",
    "TASK_SESSION_CLOSING",
}


def observation_code(exc):
    if isinstance(exc, DomainError) and (code := public_error_code(exc.code)):
        return code
    return (
        "CODING_EXECUTOR_TIMEOUT"
        if isinstance(exc, TimeoutError)
        else "CODING_EXECUTOR_OBSERVATION_FAILED"
    )


class CodingExecutor:
    can_reconcile = True

    def __init__(self, database, settings, *, persistent=True):
        self.db, self.settings = database, settings
        self.persistent = persistent
        self.artifacts = None
        self.capabilities = None
        self.catalog = None
        self.project_workspace = None

    async def command(self, sub, *args, spec=None):
        response = await execute(
            [self.settings.cli_bin, "agent", "execution", sub, *args],
            timeout=None if sub == "launch" else 15,
            excluded_env=self.settings.provider_key_environments(),
            input_data=encoded(spec).encode() if spec is not None else None,
        )
        if response["exitCode"]:
            # CLI diagnostics may contain paths or account details; keep them out of model context.
            if sub in {"launch", "close", "cleanup"} and response[
                "stderr"
            ].strip() in SESSION_REJECTIONS | {
                "SESSION_BINDING_CONFLICT",
                "WORKSPACE_BUSY",
                "WORKSPACE_OUTCOME_UNKNOWN",
                "WORKSPACE_CLEANUP_UNAVAILABLE",
                "WORKTREE_DIRTY",
                "WORKSPACE_STALE",
                "SESSIONS_INSIDE",
            }:
                raise DomainError(response["stderr"].strip())
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
        if target["kind"] == "new_session" and "baseDir" in target:
            raise DomainError("LOOSE_SESSION_USE_DIRECTORY")
        if target["kind"] == "new_project":
            target = await provision_project(self.settings, task, run)
        if target["kind"] not in {"new_session", "project", "session"}:
            raise DomainError("CODING_TARGET_ADAPTER_NOT_IMPLEMENTED")
        if spec.get("fromMessageId"):
            raise DomainError("CODING_CHECKPOINT_FORK_NOT_IMPLEMENTED")
        if (deadline := json.loads(task["budget_json"]).get("deadlineMs")) and deadline <= now_ms():
            raise DomainError("TASK_BUDGET_EXCEEDED")
        persistent = self.persistent
        if self.catalog:
            catalog = await self.catalog()
            candidate = next(
                (item for item in catalog["candidates"] if item["kind"] == spec["executor"]), None
            )
            if not candidate:
                raise DomainError("INVALID_EXECUTOR")
            persistent = persistent and candidate.get("interactive", True)
        launch = {
            "persistent": persistent,
            "promptFormat": "markdown-session",
            "shortExecutionLabel": True,
            "key": run["launch_id"],
            "executor": spec["executor"],
            "title": spec.get("title")
            or spec.get("initialIntent", {}).get("title")
            or spec["goal"].splitlines()[0][:80],
            "prompt": (
                spec["continuation"]["text"]
                if target["kind"] == "session" and spec.get("continuation", {}).get("text")
                else spec["goal"]
            ),
            "timeoutSeconds": max(
                1, math.ceil((json.loads(task["budget_json"])["deadlineMs"] - now_ms()) / 1000)
            )
            if json.loads(task["budget_json"]).get("deadlineMs")
            else 0,
        }
        swarm = await self.db.call(
            lambda db: row(
                db,
                "SELECT swarm_id,member_name FROM swarm_work_items WHERE task_id=?",
                (task["id"],),
            )
        )
        if target["kind"] != "session":
            launch["permission"] = "auto"
        if spec.get("model") and target["kind"] != "session":
            launch["model"] = spec["model"]
        continuing_session = target["kind"] == "session" and spec.get("continuation", {}).get(
            "text"
        )
        launch["prompt"] = (
            "# 任务：\n\n"
            + launch["prompt"].strip()
            + "\n\n# 开工准备\n\n"
            + managed_setup(target)
            + "\n\n"
            + execution_guide()
            + "\n\n"
            + managed_handoff(run)
        )
        if swarm:
            launch["prompt"] += "\n\n" + swarm_handoff(self.settings.cli_bin, swarm, task, run)
        if self.artifacts:
            launch["prompt"] += await professional_brief(
                self.db, self.artifacts, task, run, continuation=bool(continuing_session)
            )
        if self.capabilities:
            launch["prompt"] += await self.capabilities.brief(task, run)
        if target.get("nodeId", "local") != "local":
            raise DomainError("CODING_NODE_UNAVAILABLE")
        if target["kind"] == "session":
            if not isinstance(target.get("sessionId"), str) or not target["sessionId"]:
                raise DomainError("CODING_SESSION_ID_REQUIRED")
            if any(target.get(key) for key in ["directory", "workspaceId", "base", "remote"]):
                raise DomainError("CODING_SESSION_TARGET_CONFLICT")
            launch["sessionId"] = target["sessionId"]
        elif target["kind"] == "project":
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
        elif automatic_task_directory(target):
            workspace = await prepare_task_directory(self.db.data_root, task["id"])
            launch["directory"] = workspace["directory"]
        else:
            directory = target.get("directory") or self.settings.coding_directory
            if not isinstance(directory, (str, Path)) or not Path(directory).is_absolute():
                raise DomainError("CODING_DIRECTORY_REQUIRED")
            launch["directory"] = str(Path(directory).resolve())
        try:
            receipt = await self.launch(task, run, launch)
        except ToolPreflightError:
            raise
        except DomainError as exc:
            if exc.code == "SESSION_NOT_IDLE":
                # Go rejects this before journaling or sending the new prompt.
                raise
            if exc.code in SESSION_REJECTIONS:
                return {
                    "state": "failed",
                    "summary": exc.code,
                    "executionStarted": False,
                    "inputStopped": True,
                    "outcomeKnown": True,
                }
            await self.record(task, run, {"state": "unknown"})
            return None
        except (OSError, TimeoutError):
            await self.record(task, run, {"state": "unknown"})
            return None
        await self.record(task, run, receipt)
        return self.result(receipt)

    async def launch(self, task, run, launch):
        await prepared_authority(self.db, task, run, self.project_workspace)
        try:
            return await self.command("launch", "--file", "-", spec=launch)
        except DomainError as exc:
            if exc.code != "SESSION_TARGET_NOT_FOUND" or not launch.get("sessionId"):
                raise
            source = await self.recovery_source(task, run, launch["sessionId"])
            if not source:
                raise
        await prepared_authority(self.db, task, run, self.project_workspace)
        return await self.command(
            "launch",
            "--file",
            "-",
            spec={
                **launch,
                "resumeFrom": source["launch_id"],
                "resumeProviderId": source["agent_conversation_id"],
            },
        )

    async def recovery_source(self, task, run, session_id):
        from roami_agent.dispatch.task_sessions import assert_session_open
        from roami_agent.storage.task_provider import provider_binding

        intent = json.loads(task["intent_json"])
        continuation = intent.get("continuation", {})
        source_id = continuation.get("providerRunId") or continuation.get("runId")

        def read(db):
            assert_session_open(db, task["id"])
            source = provider_binding(db, task, source_id, run["attempt_no"] - 1)
            latest = row(
                db,
                "SELECT a.id,t.revision FROM task_attempts a JOIN tasks t ON t.id=a.task_id "
                "WHERE a.task_id=? ORDER BY a.attempt_no DESC LIMIT 1",
                (task["id"],),
            )
            if (
                not source
                or not latest
                or latest["id"] != run["id"]
                or latest["revision"] != run["task_revision"]
                or source["session_id"] != session_id
            ):
                return None
            return source

        return await self.db.call(read)

    async def record(self, task, run, receipt):
        state = {"running": "running", "cancelling": "stopping"}.get(receipt.get("state"))
        if receipt.get("result") is None and state is None:
            state = "unknown"
        observation_error = (
            public_error_code(receipt.get("observationErrorCode"))
            or "CODING_EXECUTOR_OBSERVATION_UNKNOWN"
        )

        def write(db):
            current = row(db, "SELECT * FROM task_attempts WHERE id=?", (run["id"],))
            if not current:
                return
            retain_reported_progress(db, task, run, receipt)
            if current["result_json"]:
                return
            binding = receipt.get("sessionBinding")
            if binding:
                if not isinstance(binding, dict):
                    raise DomainError("INVALID_SESSION_BINDING")
                provider_id = binding.get("providerConversationId")
                if (
                    not isinstance(provider_id, str)
                    or not provider_id
                    or binding.get("id") != receipt.get("session")
                ):
                    raise DomainError("INVALID_SESSION_BINDING")
                if current["agent_conversation_id"] not in {None, provider_id} or current[
                    "session_id"
                ] not in {None, receipt["session"]}:
                    raise DomainError("SESSION_BINDING_CONFLICT", 409)
                db.execute(
                    "UPDATE task_attempts SET agent_conversation_id=? WHERE id=?",
                    (provider_id, run["id"]),
                )
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
            was_preparing = False
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
            recovered = (
                state == "running"
                and current["state"] == "unknown"
                and bool(receipt.get("session") or current["session_id"])
                and not was_preparing
            )
            uncertain = state == "unknown" and current["state"] != "unknown"
            last_observation = (
                row(
                    db,
                    "SELECT kind,payload_json FROM events WHERE task_id=? "
                    "AND kind IN ('task.observation_unknown','task.observation_recovered') "
                    "AND json_extract(payload_json,'$.runId')=? ORDER BY id DESC LIMIT 1",
                    (task["id"], run["id"]),
                )
                if state == "unknown"
                else None
            )
            changed_reason = state == "unknown" and (
                not last_observation
                or last_observation["kind"] != "task.observation_unknown"
                or json.loads(last_observation["payload_json"]).get("errorCode")
                != observation_error
            )
            if recovered or uncertain or changed_reason:
                updated = db.execute(
                    "UPDATE tasks SET updated_ms=? WHERE id=? AND revision=? "
                    "AND state IN ('preparing','running','cancelling')",
                    (now_ms(), task["id"], run["task_revision"]),
                )
                if updated.rowcount != 1:
                    return
                event(
                    db,
                    task["origin_conversation_id"],
                    "task.observation_recovered" if recovered else "task.observation_unknown",
                    {
                        "taskId": task["id"],
                        "runId": run["id"],
                        **({"errorCode": observation_error} if state == "unknown" else {}),
                    },
                    task_id=task["id"],
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
                "WHERE a.executor_kind='cli' AND a.task_revision=t.revision AND ("
                "(a.result_json IS NULL AND t.state IN ('preparing','running','cancelling')) OR "
                "(t.state='interrupted' AND a.state='unknown' AND json_extract(a.result_json,'$.outcomeKnown')=0)) "
                "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.kind='task.run' AND j.aggregate_id=t.id AND j.state IN ('queued','running')) "
                "ORDER BY CASE WHEN t.state='interrupted' THEN 1 ELSE 0 END,a.started_ms LIMIT 100",
            )
        )
        expired = []
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
                    continue
            except (DomainError, OSError, TimeoutError) as exc:
                # A failed observation is neither a terminal report nor permission to relaunch.
                await self.record(
                    task, run, {"state": "unknown", "observationErrorCode": observation_code(exc)}
                )
            if (
                task["state"] != "interrupted"
                and (deadline := json.loads(task["budget_json"]).get("deadlineMs"))
                and deadline <= now_ms()
            ):
                await self.cancel(task, run)
                expired.append((task, run))
        return expired

    async def cancel(self, task, run):
        try:
            receipt = await self.command("cancel", "--key", run["launch_id"])
            await self.record(task, run, receipt)
        except (DomainError, OSError, TimeoutError) as exc:
            await self.record(
                task, run, {"state": "unknown", "observationErrorCode": observation_code(exc)}
            )
