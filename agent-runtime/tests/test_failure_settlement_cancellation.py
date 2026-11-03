"""Failure bookkeeping survives cancellation without promoting unknown writes."""

import asyncio
import json
from pathlib import Path

import pytest
from test_coordinator_handoff import call
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError, ToolPreflightError
from roami_agent.storage.database import row, rows

CONTROLS = json.loads(
    (
        Path(__file__).resolve().parents[2] / "cases/case-110-mech-fs01/input/controls.json"
    ).read_text()
)


@pytest.mark.parametrize("kind", CONTROLS["failure_kinds"])
@pytest.mark.parametrize("after_record", CONTROLS["pause_after_turn_record"])
@pytest.mark.parametrize("signals", CONTROLS["cancellation_signals"])
async def test_cancel_during_failure_bookkeeping_settles_before_applying_steering(
    store, monkeypatch, kind, after_record, signals
):
    runtime = Runtime(store, ConversationModel())
    entered, release = asyncio.Event(), asyncio.Event()
    original = runtime.dispatch.end_prepared_turn
    executions = []

    class FailedNative:
        def requires_workspace(self, task):
            return False

        async def run(self, task, run, *, turn):
            executions.append(run["id"])
            if kind == "write":
                mid = await runtime.journal.start(turn)
                with pytest.raises(DomainError, match="TOOL_OUTCOME_UNKNOWN"):
                    await runtime.gateway.invoke(
                        turn,
                        mid,
                        call("uncertain_write", {}),
                        "worker",
                        {
                            "owner": "alice",
                            "conversation": turn["conversation_id"],
                            "turnId": turn["id"],
                        },
                    )
                raise OSError("transport lost after a write")
            raise DomainError(
                "NATIVE_WORKSPACE_OUTCOME_UNKNOWN"
                if kind == "unknown"
                else CONTROLS["known_failure"]
            )

    async def paused(turn, state, code):
        if after_record:
            await original(turn, state, code)
        entered.set()
        await release.wait()
        if not after_record:
            await original(turn, state, code)

    runtime.dispatch.native_executor = FailedNative()
    monkeypatch.setattr(runtime.dispatch, "end_prepared_turn", paused)
    if kind == "write":
        from roami_agent.protocol.tools import Tool, object_schema

        async def unknown_write(args, binding):
            raise DomainError("TOOL_OUTCOME_UNKNOWN")

        runtime.tools.add(
            Tool(
                "uncertain_write",
                "Synthetic uncertain write",
                object_schema({}),
                unknown_write,
                effect="write",
            )
        )
    try:
        c = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", c["id"], CONTROLS["goal"], key="task", record_intent=True
        )
        await runtime.scheduler._scan()
        await asyncio.wait_for(entered.wait(), 2)
        handle = next(
            item["handle"] for item in runtime.active.values() if item["task"] == task["id"]
        )
        operation = await runtime.tasks.revisions.request(
            "alice", task["id"], CONTROLS["continuation"], 1, "steer"
        )
        await runtime.dispatch.cancel()
        for _ in range(signals - 1):
            await asyncio.sleep(0)
            handle.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await handle
        await asyncio.sleep(0)
        assert not runtime.active
        verification = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE aggregate_id=? AND kind='task.verify' AND state='queued'",
                (task["id"],),
            )
        )
        if verification:
            await runtime.dispatch.verify(verification)
        await runtime.dispatch.cancel()
        await runtime.tasks.revisions.advance()
        receipt = await runtime.tasks.revisions.get("alice", task["id"], operation["operationId"])
        attempts = await store.call(
            lambda db: rows(
                db,
                "SELECT * FROM task_attempts WHERE task_id=? ORDER BY task_revision",
                (task["id"],),
            )
        )
        old = attempts[0]
        assert old["result_json"] is not None
        result = json.loads(old["result_json"])
        assert len(executions) == 1
        assert not await store.call(
            lambda db: row(
                db,
                "SELECT t.id FROM turns t JOIN task_attempts a ON a.native_branch_id=t.branch_id WHERE a.id=? AND t.state='running'",
                (old["id"],),
            )
        )
        if kind == "known":
            assert receipt["state"] == "applied" and receipt["revision"] == 2
            assert old["state"] == "failed" and len(attempts) == 2
            assert result["summary"] == result["errorCode"] == CONTROLS["known_failure"]
            assert attempts[1]["state"] == "accepted"
        else:
            assert (
                receipt["state"] == "blocked" and receipt["errorCode"] == "TASK_OUTCOME_UNRESOLVED"
            )
            assert old["state"] == "unknown" and len(attempts) == 1
            assert result["outcomeKnown"] is False and result["retryable"] is False
            assert result["summary"] == (
                "TOOL_STOP_UNCONFIRMED" if kind == "write" else "NATIVE_WORKSPACE_OUTCOME_UNKNOWN"
            )
    finally:
        release.set()
        await runtime.close()


@pytest.mark.parametrize(
    "failure,code",
    [
        (OSError(), "EXECUTION_FAILED"),
        (TimeoutError(), "EXECUTION_TIMEOUT"),
        (ToolPreflightError("BROWSER_CDP_UNAVAILABLE"), "BROWSER_CDP_UNAVAILABLE"),
    ],
)
async def test_failure_without_cancellation_keeps_original_outcome(store, failure, code):
    runtime = Runtime(store, ConversationModel())

    class FailedNative:
        def requires_workspace(self, task):
            return False

        async def run(self, *args, **kwargs):
            raise failure

    runtime.dispatch.native_executor = FailedNative()
    try:
        c = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", c["id"], CONTROLS["goal"], key="task", record_intent=True
        )
        await runtime.scheduler._scan()
        handle = next(
            item["handle"] for item in runtime.active.values() if item["task"] == task["id"]
        )
        await handle
        run = await store.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
        )
        assert run["state"] == "failed"
        result = json.loads(run["result_json"])
        assert result["summary"] == result["errorCode"] == code
        if isinstance(failure, ToolPreflightError):
            assert result["failedStep"] == {"phase": "preflight", "executionStarted": False}
        verify = await store.call(
            lambda db: row(
                db, "SELECT * FROM jobs WHERE aggregate_id=? AND kind='task.verify'", (task["id"],)
            )
        )
        await runtime.dispatch.verify(verify)
        assert (await runtime.tasks.get("alice", task["id"]))["task"]["state"] == "failed"
    finally:
        await runtime.close()


async def test_shutdown_during_failure_record_preserves_failure_for_recovery(store, monkeypatch):
    runtime = Runtime(store, ConversationModel())
    entered, release = asyncio.Event(), asyncio.Event()
    original = runtime.dispatch.end_prepared_turn

    class FailedNative:
        def requires_workspace(self, task):
            return False

        async def run(self, *args, **kwargs):
            raise DomainError(CONTROLS["known_failure"])

    async def paused(*args):
        entered.set()
        await release.wait()
        await original(*args)

    runtime.dispatch.native_executor = FailedNative()
    monkeypatch.setattr(runtime.dispatch, "end_prepared_turn", paused)
    try:
        c = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", c["id"], CONTROLS["goal"], key="task", record_intent=True
        )
        await runtime.scheduler._scan()
        await asyncio.wait_for(entered.wait(), 2)
        handle = next(
            item["handle"] for item in runtime.active.values() if item["task"] == task["id"]
        )
        handle.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await handle
        run = await store.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
        )
        assert run["state"] == "failed"
        assert json.loads(run["result_json"])["summary"] == CONTROLS["known_failure"]
        verify = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE aggregate_id=? AND kind='task.verify' AND state='queued'",
                (task["id"],),
            )
        )
        assert verify is not None
        await runtime.dispatch.verify(verify)
        assert (await runtime.tasks.get("alice", task["id"]))["task"]["state"] == "failed"
    finally:
        release.set()
        await runtime.close()
