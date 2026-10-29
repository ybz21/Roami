"""Attachment collection limits are not evidence that unreported side files are missing."""

import json
import sys
from contextlib import asynccontextmanager

import pytest
from test_routing_policy import setup
from test_runtime import ConversationModel
from test_task_delivery_benchmark import admit, mark

from roami_agent.app import Runtime
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.database import row


@pytest.mark.parametrize("missing_observed", [False, True])
async def test_native_result_does_not_mark_uncaptured_side_files_unavailable(
    store, tmp_path, missing_observed
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    class Worker:
        model = "attachment-scope-fixture"
        calls = 0

        async def stream(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                for index, name in enumerate(
                    [*[f"analysis-{i}.py" for i in range(13)], "answer.txt"]
                ):
                    yield ModelEvent(
                        "tool",
                        {
                            "id": "create-" + str(index),
                            "function": {
                                "name": "write",
                                "arguments": json.dumps(
                                    {
                                        "path": name,
                                        "expectedSha256": None,
                                        "content": "final output"
                                        if name == "answer.txt"
                                        else "# intermediate analysis\n",
                                    }
                                ),
                            },
                        },
                    )
            elif self.calls == 2 and missing_observed:
                yield ModelEvent(
                    "tool",
                    {
                        "id": "remove-side-file",
                        "function": {
                            "name": "bash",
                            "arguments": json.dumps(
                                {
                                    "argv": [
                                        sys.executable,
                                        "-c",
                                        "from pathlib import Path; Path('analysis-0.py').unlink()",
                                    ]
                                }
                            ),
                        },
                    },
                )
            else:
                yield ModelEvent("text", "Report: [answer](answer.txt)")

    @asynccontextmanager
    async def prepared(*args, **kwargs):
        yield {"workspaceId": "fixture", "directory": str(workspace)}

    runtime = Runtime(
        store, ConversationModel(), worker_model=Worker(), memory_model=ConversationModel()
    )
    runtime.dispatch.native_executor.workspace_factory = prepared
    try:
        c = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            c["id"],
            "Write answer.txt",
            key="side-files",
            record_intent=True,
            target={"kind": "new_session", "directory": str(workspace)},
        )
        job = await store.call(
            lambda db: row(
                db, "SELECT * FROM jobs WHERE kind='task.run' AND aggregate_id=?", (task["id"],)
            )
        )
        await runtime.dispatch.run(job)
        attempt = await store.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
        )
        result = json.loads(attempt["result_json"])
        missing = result.get("unavailableOutputs", [])
        assert len(missing) == int(missing_observed)
        if missing_observed:
            assert missing[0]["sourcePath"] == "analysis-0.py"
        assert result["artifactRefs"][0]["name"] == "answer.txt"
        assert result["artifactsTruncated"] is True
        stored = await runtime.artifacts.list("alice", task_id=task["id"])
        assert len(stored) == 12
        assert (await runtime.artifacts.read("alice", result["artifactRefs"][0]["id"]))[
            1
        ] == b"final output"
        assert (workspace / "analysis-12.py").is_file()
    finally:
        await runtime.close()


async def test_explicitly_reported_output_still_unavailable_when_retention_is_full(store, tmp_path):
    runtime, _, _, _, binding = await setup(store)
    try:
        task = await admit(
            runtime, binding, "Deliver all reports", "reported-overflow", executor="codex"
        )
        for index in range(13):
            (tmp_path / f"report-{index}.txt").write_text("report")
        await mark(
            runtime,
            task,
            "waiting_user",
            {
                "state": "succeeded",
                "summary": "\n".join(
                    f"[report-{index}](report-{index}.txt)" for index in range(12)
                ),
                "output": "[last](report-12.txt)",
                "workspace": {"directory": str(tmp_path)},
            },
        )
        detail = await runtime.tasks.get("alice", task["id"])
        assert len(detail["delivery"]["artifacts"]) == 12
        assert detail["delivery"]["unavailable"] == [
            {
                "sourcePath": "report-12.txt",
                "runId": detail["attempts"][0]["id"],
                "state": "unavailable",
            }
        ]
        assert detail["task"]["state"] == "waiting_user"
    finally:
        await runtime.close()
