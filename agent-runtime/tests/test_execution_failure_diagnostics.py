"""Task result diagnostics retain safe causes and keep uncertain writes interrupted."""

import json

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.dispatch.runner import execution_failure
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row


@pytest.mark.parametrize("kind", ["timeout", "os", "workspace"])
async def test_dispatch_failure_result_survives_verification(store, kind):
    class Executor:
        async def run(self, task, run):
            if kind == "timeout":
                raise TimeoutError("private URL and credentials")
            if kind == "os":
                raise OSError("private filesystem path")
            try:
                raise DomainError("MODEL_HTTP_401")
            except DomainError as cause:
                raise DomainError("NATIVE_WORKSPACE_OUTCOME_UNKNOWN") from cause

    runtime = Runtime(store, ConversationModel(), executor=Executor())
    try:
        c = await runtime.conversations.create("alice")
        await runtime.tasks.create(
            "alice", c["id"], "Work", key="failure", executor="codex", record_intent=True
        )
        job = await store.call(lambda db: row(db, "SELECT * FROM jobs WHERE kind='task.run'"))
        await runtime.dispatch.run(job)
        verification = await store.call(
            lambda db: row(db, "SELECT * FROM jobs WHERE kind='task.verify'")
        )
        if verification:
            await runtime.dispatch.verify(verification)
        attempt = await store.call(lambda db: row(db, "SELECT * FROM task_attempts"))
        current = await store.call(lambda db: row(db, "SELECT * FROM tasks"))
        result = json.loads(attempt["result_json"])
        expected = {
            "timeout": "EXECUTION_TIMEOUT",
            "os": "EXECUTION_FAILED",
            "workspace": "NATIVE_WORKSPACE_OUTCOME_UNKNOWN",
        }[kind]
        assert result["summary"] == result["errorCode"] == expected
        assert current["state"] == ("interrupted" if kind == "workspace" else "failed")
        assert "private" not in attempt["result_json"]
        if kind == "workspace":
            assert result["outcomeKnown"] is False and result["retryable"] is False
            assert result["failure"]["causeCodes"] == [expected, "MODEL_HTTP_401"]
        else:
            assert result["failure"]["exceptionType"] == (
                "TimeoutError" if kind == "timeout" else "OSError"
            )
    finally:
        await runtime.close()


def test_diagnostics_bound_cycles_and_reject_private_codes():
    cause = DomainError("private URL")
    outer = DomainError("TOOL_OUTCOME_UNKNOWN")
    cause.__cause__ = outer
    outer.__cause__ = cause
    assert execution_failure(outer)["failure"] == {
        "exceptionType": "DomainError",
        "causeCodes": ["TOOL_OUTCOME_UNKNOWN"],
    }
