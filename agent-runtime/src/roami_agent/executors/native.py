"""Native branches bind to Go-prepared workspaces before model/tool admission."""

import asyncio
import json

from roami_agent.conversation.activity_events import activity_event as event
from roami_agent.executors.workspace import hold_workspace
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row
from roami_agent.storage.task_deliverables import TaskDeliverables


class NativeExecutor:
    def __init__(
        self,
        run_turn,
        database=None,
        settings=None,
        workspace_factory=hold_workspace,
        *,
        resources=None,
        artifacts=None,
    ):
        self.run_turn, self.db, self.settings = run_turn, database, settings
        self.workspace_factory = workspace_factory
        self.resources, self.artifacts = resources, artifacts

    def requires_workspace(self, task):
        target = json.loads(task["intent_json"])["target"]
        if target["kind"] == "new_session" and target.get("resourceOnly") is True:
            return False
        return (
            target["kind"] != "new_session"
            or target.get("nodeId", "local") != "local"
            or bool(target.get("directory") or getattr(self.settings, "coding_directory", None))
        )

    async def run(self, task, run, *, turn=None):
        try:
            return await self._run(task, run, turn=turn)
        finally:
            if self.resources:
                await self.resources.release_task(task["owner_id"], task["id"], run["id"])

    async def _run(self, task, run, *, turn=None):
        if turn is None or turn["branch_id"] != run["native_branch_id"]:
            raise DomainError("NATIVE_EXECUTION_CONTEXT_MISMATCH")

        deadline = json.loads(task["budget_json"]).get("deadlineMs")
        remaining = max(0, (deadline - now_ms()) / 1000) if deadline else None

        async def execute(prepared):
            text = await self.run_turn(
                dict(
                    prepared,
                    executionRunId=run["id"],
                    executionTimeoutSeconds=remaining,
                ),
                "research"
                if json.loads(task["intent_json"])["target"].get("resourceOnly") is True
                else "worker",
                task_id=task["id"],
            )
            uncertain = await self.db.call(
                lambda db: row(
                    db,
                    "SELECT id FROM tool_calls WHERE turn_id=? AND effect='write' "
                    "AND state IN ('planned','running','unknown') LIMIT 1",
                    (prepared["id"],),
                )
            )
            if uncertain:
                raise DomainError("TOOL_OUTCOME_UNKNOWN")
            result = {"state": "succeeded", "summary": text}
            if len(text.encode()) > 6000 and self.artifacts:
                source = await self.db.call(
                    lambda db: row(
                        db,
                        "SELECT id FROM messages WHERE turn_id=? AND role='assistant' AND status='completed' ORDER BY seq DESC LIMIT 1",
                        (prepared["id"],),
                    )
                )
                result.update(
                    summary=text.encode()[:6000].decode(errors="ignore"),
                    summaryTruncated=True,
                    resultRef={
                        "conversationId": prepared["conversation_id"],
                        "branchId": prepared["branch_id"],
                        "messageId": source["id"] if source else None,
                    },
                )
                try:
                    await self.artifacts.put(
                        task["owner_id"],
                        text.encode(),
                        mime_type="text/plain",
                        name="task-result.txt",
                        task_id=task["id"],
                        message_id=source["id"] if source else None,
                        metadata={"source": "native_result", "runId": run["id"]},
                    )
                except (DomainError, OSError) as exc:
                    result["artifactError"] = (
                        exc.code if isinstance(exc, DomainError) else "ARTIFACT_STORAGE_UNAVAILABLE"
                    )
            if self.artifacts:
                delivery = await TaskDeliverables(self.artifacts).collect(
                    task["owner_id"],
                    {
                        "task": task,
                        "attempts": [{"id": run["id"], "finishedMs": now_ms(), "result": result}],
                    },
                )
                if delivery["unavailable"]:
                    result["unavailableOutputs"] = delivery["unavailable"]
                references = await self.artifacts.for_attempt(
                    task["owner_id"], task["id"], run["id"], reported_text=text
                )
                references = list(
                    {item["id"]: item for item in [*delivery["artifacts"], *references]}.values()
                )
                if references:
                    result["artifactRefs"] = [
                        {
                            key: item[key]
                            for key in [
                                "id",
                                "name",
                                "mimeType",
                                "sizeBytes",
                                "sha256",
                                "downloadUrl",
                            ]
                        }
                        for item in references[:4]
                    ]
                    result["artifactsTruncated"] = len(references) > 4
            return result

        async with asyncio.timeout(remaining):
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
