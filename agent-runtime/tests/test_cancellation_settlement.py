"""A second stop request must not abandon the first stop's durable cleanup."""

import asyncio
import json
from pathlib import Path

import pytest
from test_coordinator_handoff import call
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row, rows

CONTROLS = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "cases/case-78-mech-ns01/input/cancellation-settlement.json"
    ).read_text()
)


@pytest.mark.parametrize("after_record", CONTROLS["after_record"])
@pytest.mark.parametrize("unknown_write", CONTROLS["unknown_write"])
@pytest.mark.parametrize("intent", CONTROLS["intents"])
async def test_repeated_cancel_finishes_stop_receipt(
    store, monkeypatch, after_record, unknown_write, intent
):
    runtime = Runtime(store, ConversationModel())
    executing, settling, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = runtime.dispatch.end_prepared_turn
    executions = []

    class Native:
        def requires_workspace(self, task):
            return False

        async def run(self, task, run, *, turn):
            executions.append(run["id"])
            if unknown_write:
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
            executing.set()
            await asyncio.Event().wait()

    async def paused(turn, state, code):
        if after_record:
            await original(turn, state, code)
        settling.set()
        await release.wait()
        if not after_record:
            await original(turn, state, code)

    runtime.dispatch.native_executor = Native()
    monkeypatch.setattr(runtime.dispatch, "end_prepared_turn", paused)
    if unknown_write:
        from roami_agent.protocol.tools import Tool, object_schema

        async def uncertain_write(args, binding):
            raise DomainError("TOOL_OUTCOME_UNKNOWN")

        runtime.tools.add(
            Tool(
                "uncertain_write",
                "Synthetic uncertain write",
                object_schema({}),
                uncertain_write,
                effect="write",
            )
        )
    handle = None
    try:
        c = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", c["id"], CONTROLS["goal"], key="original", record_intent=True
        )
        await runtime.scheduler._scan()
        await asyncio.wait_for(executing.wait(), 2)
        handle = next(a["handle"] for a in runtime.active.values() if a["task"] == task["id"])
        if intent == "continue":
            operation = await runtime.tasks.revisions.request(
                "alice", task["id"], CONTROLS["continuation"], 1, "continue"
            )
        elif intent == "stop":
            await runtime.tasks.cancel("alice", task["id"])
        handle.cancel()
        await asyncio.wait_for(settling.wait(), 2)
        for _ in range(CONTROLS["extra_cancel_signals"]):
            handle.cancel()
            await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await handle
        await asyncio.sleep(0)
        assert not runtime.active
        current = await store.call(
            lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],))
        )
        old = await store.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
        )
        assert not await store.call(
            lambda db: row(
                db,
                "SELECT id FROM turns WHERE branch_id=? AND state='running'",
                (old["native_branch_id"],),
            )
        )
        assert len(executions) == 1
        if unknown_write:
            assert current["state"] == "interrupted" and old["state"] == "unknown"
            result = json.loads(old["result_json"])
            assert result["summary"] == "TOOL_STOP_UNCONFIRMED" and result["outcomeKnown"] is False
            pending = await store.call(
                lambda db: rows(db, "SELECT state FROM tool_calls WHERE effect='write'")
            )
            assert [p["state"] for p in pending] == ["unknown"]
        elif intent == "shutdown":
            assert current["state"] == "interrupted"
            assert old["result_json"] is None
        else:
            assert old["result_json"] is not None
            assert json.loads(old["result_json"])["state"] == "cancelled"
            job = await store.call(
                lambda db: row(
                    db,
                    "SELECT * FROM jobs WHERE kind='task.verify' AND aggregate_id=?",
                    (task["id"],),
                )
            )
            await runtime.dispatch.verify(job)
        if intent == "continue":
            await runtime.tasks.revisions.advance()
            receipt = await runtime.tasks.revisions.get(
                "alice", task["id"], operation["operationId"]
            )
            assert receipt["state"] == ("blocked" if unknown_write else "applied")
            assert receipt["errorCode"] == ("TASK_OUTCOME_UNRESOLVED" if unknown_write else None)
            assert receipt["revision"] == (1 if unknown_write else 2)
        elif intent == "stop" and not unknown_write:
            current = await runtime.tasks.get("alice", task["id"])
            assert current["task"]["state"] == "cancelled"
    finally:
        release.set()
        if handle is not None and not handle.done():
            handle.cancel()
            await asyncio.gather(handle, return_exceptions=True)
        await runtime.close()


@pytest.mark.parametrize("after_commit", [False, True])
@pytest.mark.parametrize("preparing", [False, True])
async def test_repeated_cancel_during_start_recovery(store, monkeypatch, after_commit, preparing):
    await startup_control(store, monkeypatch, after_commit, preparing, "continue")


@pytest.mark.parametrize("preparing", [False, True])
async def test_repeated_shutdown_during_committed_start_recovery(store, monkeypatch, preparing):
    await startup_control(store, monkeypatch, True, preparing, "shutdown")


async def startup_control(store, monkeypatch, after_commit, preparing, intent):
    runtime = Runtime(store, ConversationModel())
    entered, release = asyncio.Event(), asyncio.Event()
    original = store.call
    executions = []

    class Native:
        def requires_workspace(self, task):
            return preparing

        async def run(self, *args, **kwargs):
            executions.append(True)

    runtime.dispatch.native_executor = Native()
    c = await runtime.conversations.create("alice")
    task = await runtime.tasks.create(
        "alice", c["id"], CONTROLS["goal"], key="start", record_intent=True
    )
    job = await original(lambda db: row(db, "SELECT * FROM jobs WHERE kind='task.run'"))

    async def paused(function, *, write=False):
        if function.__name__ != "start" or not write:
            return await original(function, write=write)
        if after_commit:
            result = await original(function, write=write)
        entered.set()
        await release.wait()
        return result if after_commit else await original(function, write=write)

    monkeypatch.setattr(store, "call", paused)
    handle = asyncio.create_task(runtime.dispatch.run(job))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        if intent == "continue":
            operation = await runtime.tasks.revisions.request(
                "alice", task["id"], CONTROLS["continuation"], 1, "start-continue"
            )
        handle.cancel()
        await asyncio.sleep(0)
        for _ in range(CONTROLS["extra_cancel_signals"]):
            handle.cancel()
            await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await handle
        assert not executions
        assert not await original(lambda db: row(db, "SELECT id FROM turns WHERE state='running'"))
        if intent == "shutdown":
            current = await runtime.tasks.get("alice", task["id"])
            assert current["task"]["state"] == "interrupted"
        else:
            await runtime.dispatch.cancel()
            verification = await original(
                lambda db: row(db, "SELECT * FROM jobs WHERE kind='task.verify' AND state='queued'")
            )
            if verification:
                await runtime.dispatch.verify(verification)
            await runtime.tasks.revisions.advance()
            receipt = await runtime.tasks.revisions.get(
                "alice", task["id"], operation["operationId"]
            )
            assert receipt["state"] == "applied" and receipt["revision"] == 2
    finally:
        release.set()
        if not handle.done():
            handle.cancel()
            await asyncio.gather(handle, return_exceptions=True)
        monkeypatch.setattr(store, "call", original)
        await runtime.close()
