"""Native diagnostics retain provenance without granting task or publication outcomes."""

import copy
import json

import pytest
from test_task_reported_progress import reported_task

from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.storage.native_tool_observations import tool_diagnostic


async def diagnostic_task(store, tmp_path):
    runtime, task, run, receipt, page = await reported_task(store, tmp_path)
    receipt.pop("progress")
    receipt["state"] = "running"
    receipt["reportedToolError"] = {
        "source": "provider_transcript",
        "code": "CLAUDE_AUTO_CLASSIFIER_UNAVAILABLE",
        "tool": "Bash",
        "toolUseId": "original-tool",
        "directory": str(page),
        "providerConversationId": "provider-report",
        "promptId": "original-prompt",
        "sourceDigest": "b" * 64,
        "observedMs": 123456,
    }
    return runtime, task, run, receipt


async def model_status(runtime, task, *, include=False):
    return await runtime.tools.invoke(
        {
            "function": {
                "name": "task_status",
                "arguments": json.dumps(
                    {
                        "taskId": task["id"],
                        "includeResult": include,
                    }
                ),
            }
        },
        "main",
        {"owner": "alice", "conversation": task["origin_conversation_id"]},
    )


async def test_diagnostic_is_idempotent_historical_and_never_an_execution_result(store, tmp_path):
    runtime, task, run, receipt = await diagnostic_task(store, tmp_path)
    executor = CodingExecutor(store, Settings())
    try:
        await executor.record(task, run, receipt)
        await executor.record(task, run, receipt)
        detail = await runtime.tasks.get("alice", task["id"])
        diagnostic = detail["attempts"][0]["toolDiagnostic"]
        assert diagnostic["reported"] == receipt["reportedToolError"]
        assert diagnostic["diagnosticOnly"] is True
        assert detail["task"]["state"] == detail["attempts"][0]["state"] == "running"
        assert detail["attempts"][0]["result"] is None
        assert detail["attempts"][0]["finishedMs"] is None
        assert not detail["delivery"]["artifacts"]
        assert "executorToolDiagnostic" not in (await model_status(runtime, task))[0]
        status = (await model_status(runtime, task, include=True))[0]
        assert status["executorToolDiagnostic"] == diagnostic and status["executorResult"] is None
        later = copy.deepcopy(receipt)
        later.pop("reportedToolError")
        await executor.record(task, run, later)
        assert (await runtime.tasks.get("alice", task["id"]))["attempts"][0][
            "toolDiagnostic"
        ] == diagnostic
        assert (
            await store.call(
                lambda db: db.execute(
                    "SELECT count(*) FROM events WHERE task_id=? AND kind='task.execution_tool_diagnostic'",
                    (task["id"],),
                ).fetchone()[0]
            )
            == 1
        )
        assert (
            await store.call(
                lambda db: db.execute(
                    "SELECT count(*) FROM jobs WHERE kind IN ('task.verify','task.yield') AND aggregate_id=?",
                    (task["id"],),
                ).fetchone()[0]
            )
            == 0
        )
        assert (
            await store.call(
                lambda db: tool_diagnostic(db, task["id"], "other-run", run["task_revision"])
            )
            is None
        )
        assert (
            await store.call(
                lambda db: tool_diagnostic(db, task["id"], run["id"], run["task_revision"] + 1)
            )
            is None
        )
        with pytest.raises(DomainError, match="TASK_NOT_FOUND"):
            await runtime.tasks.get("bob", task["id"])
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("source", "terminal_capture"),
        ("code", "SOME_OTHER_ERROR"),
        ("providerConversationId", "foreign"),
        ("sourceDigest", "not-a-digest"),
        ("promptId", ""),
        ("toolUseId", ""),
        ("tool", "x" * 257),
        ("observedMs", True),
        ("observedMs", 0),
        ("directory", "relative"),
    ],
)
async def test_unbound_or_malformed_diagnostic_does_not_enter_the_ledger(
    store, tmp_path, field, value
):
    runtime, task, run, receipt = await diagnostic_task(store, tmp_path)
    receipt["reportedToolError"][field] = value
    try:
        with pytest.raises(DomainError, match="INVALID_EXECUTOR_TOOL_DIAGNOSTIC"):
            await CodingExecutor(store, Settings()).record(task, run, receipt)
        detail = await runtime.tasks.get("alice", task["id"])
        assert "toolDiagnostic" not in detail["attempts"][0]
    finally:
        await runtime.close()


async def test_project_escape_provider_changes_and_same_digest_conflicts_are_rejected(
    store, tmp_path
):
    runtime, task, run, receipt = await diagnostic_task(store, tmp_path)
    executor = CodingExecutor(store, Settings())
    try:
        await executor.record(task, run, receipt)
        original = (await runtime.tasks.get("alice", task["id"]))["attempts"][0]["toolDiagnostic"]
        changed = copy.deepcopy(receipt)
        changed["reportedToolError"]["observedMs"] += 1
        with pytest.raises(DomainError, match="EXECUTOR_TOOL_DIAGNOSTIC_CONFLICT"):
            await executor.record(task, run, changed)
        changed = copy.deepcopy(receipt)
        changed["reportedToolError"]["directory"] = str(tmp_path)
        with pytest.raises(DomainError, match="INVALID_EXECUTOR_TOOL_DIAGNOSTIC"):
            await executor.record(task, run, changed)
        changed = copy.deepcopy(receipt)
        changed["reportedToolError"]["providerConversationId"] = "foreign"
        changed["sessionBinding"]["providerConversationId"] = "foreign"
        with pytest.raises(DomainError, match="INVALID_EXECUTOR_TOOL_DIAGNOSTIC"):
            await executor.record(task, run, changed)
        assert (await runtime.tasks.get("alice", task["id"]))["attempts"][0][
            "toolDiagnostic"
        ] == original
    finally:
        await runtime.close()


async def test_recorded_workspace_fallback_and_latest_provider_time_not_arrival_order(
    store, tmp_path
):
    runtime, task, run, receipt = await diagnostic_task(store, tmp_path)
    executor = CodingExecutor(store, Settings())
    try:
        await executor.record(task, run, receipt)
        original = (await runtime.tasks.get("alice", task["id"]))["attempts"][0]["toolDiagnostic"]
        delayed = copy.deepcopy(receipt)
        delayed.pop("workspace")
        delayed["reportedToolError"].update(sourceDigest="c" * 64, observedMs=123455)
        await executor.record(task, run, delayed)
        assert (await runtime.tasks.get("alice", task["id"]))["attempts"][0][
            "toolDiagnostic"
        ] == original
    finally:
        await runtime.close()
