"""Cancellation must not strand a committed Native start outside cleanup."""

import asyncio
import json
from pathlib import Path

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row

SCENARIOS = json.loads(
    (Path(__file__).parent / "fixtures/native-start-cancellation.json").read_text()
)


@pytest.mark.parametrize("after_commit", SCENARIOS["afterCommit"])
@pytest.mark.parametrize("preparing", SCENARIOS["preparing"])
async def test_cancelled_start_releases_native_turn_and_admits_user_continuation(
    store, monkeypatch, after_commit, preparing
):
    runtime = Runtime(store, ConversationModel())
    entered, release = asyncio.Event(), asyncio.Event()
    original = store.call
    executions = []

    class Native:
        def requires_workspace(self, task):
            return preparing

        async def run(self, *args, **kwargs):
            executions.append(True)
            raise AssertionError("Cancelled startup must not execute work")

    runtime.dispatch.native_executor = Native()
    conversation = await runtime.conversations.create("alice")
    task = await runtime.tasks.create(
        "alice", conversation["id"], SCENARIOS["goal"], key="original", record_intent=True
    )
    job = await original(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='task.run' AND aggregate_id=?", (task["id"],)
        )
    )

    async def paused_start(function, *, write=False):
        if function.__name__ != "start" or not write:
            return await original(function, write=write)
        if after_commit:
            result = await original(function, write=write)
        entered.set()
        await release.wait()
        return result if after_commit else await original(function, write=write)

    monkeypatch.setattr(store, "call", paused_start)
    handle = asyncio.create_task(runtime.dispatch.run(job))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        operation = await runtime.tasks.revisions.request(
            "alice", task["id"], SCENARIOS["continuation"], 1, "continue"
        )
        handle.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await handle
        monkeypatch.setattr(store, "call", original)
        await runtime.dispatch.cancel()
        verification = await original(
            lambda db: row(db, "SELECT * FROM jobs WHERE kind='task.verify' AND state='queued'")
        )
        if verification:
            await runtime.dispatch.verify(verification)
        await runtime.tasks.revisions.advance()
        receipt = await runtime.tasks.revisions.get("alice", task["id"], operation["operationId"])
        assert receipt["state"] == "applied" and receipt["revision"] == 2
        assert not executions
        old_turns = await original(
            lambda db: list(db.execute("SELECT state FROM turns WHERE trigger_kind='user'"))
        )
        assert len(old_turns) == int(after_commit)
        assert all(turn[0] != "running" for turn in old_turns)
        previous = await original(
            lambda db: row(
                db, "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=1", (task["id"],)
            )
        )
        assert previous["state"] == "cancelled"
        assert json.loads(previous["result_json"])["state"] == "cancelled"
    finally:
        release.set()
        if not handle.done():
            handle.cancel()
            await asyncio.gather(handle, return_exceptions=True)
        monkeypatch.setattr(store, "call", original)
        await runtime.close()


async def test_start_failure_keeps_original_error_and_does_not_invent_task_result(
    store, monkeypatch
):
    runtime = Runtime(store, ConversationModel())
    original = store.call
    conversation = await runtime.conversations.create("alice")
    task = await runtime.tasks.create(
        "alice", conversation["id"], SCENARIOS["goal"], key="original", record_intent=True
    )
    job = await original(lambda db: row(db, "SELECT * FROM jobs WHERE kind='task.run'"))

    async def unavailable(function, *, write=False):
        if function.__name__ == "start" and write:
            raise DomainError("WRITER_BUSY", 503)
        return await original(function, write=write)

    monkeypatch.setattr(store, "call", unavailable)
    try:
        with pytest.raises(DomainError, match="WRITER_BUSY"):
            await runtime.dispatch.run(job)
        current = await original(
            lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],))
        )
        assert current["state"] == "queued"
        attempt = await original(
            lambda db: row(
                db, "SELECT state,result_json FROM task_attempts WHERE task_id=?", (task["id"],)
            )
        )
        assert attempt["state"] == "accepted" and attempt["result_json"] is None
    finally:
        monkeypatch.setattr(store, "call", original)
        await runtime.close()


async def test_shutdown_cancellation_after_committed_start_leaves_no_running_native_turn(
    store, monkeypatch
):
    runtime = Runtime(store, ConversationModel())
    original = store.call
    entered, release = asyncio.Event(), asyncio.Event()
    conversation = await runtime.conversations.create("alice")
    task = await runtime.tasks.create(
        "alice", conversation["id"], SCENARIOS["goal"], key="original", record_intent=True
    )
    job = await original(lambda db: row(db, "SELECT * FROM jobs WHERE kind='task.run'"))

    async def paused(function, *, write=False):
        result = await original(function, write=write)
        if function.__name__ == "start" and write:
            entered.set()
            await release.wait()
        return result

    monkeypatch.setattr(store, "call", paused)
    handle = asyncio.create_task(runtime.dispatch.run(job))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        handle.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await handle
        current = await original(
            lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],))
        )
        assert current["state"] == "interrupted"
        assert not await original(lambda db: row(db, "SELECT 1 FROM turns WHERE state='running'"))
    finally:
        release.set()
        if not handle.done():
            handle.cancel()
            await asyncio.gather(handle, return_exceptions=True)
        monkeypatch.setattr(store, "call", original)
        await runtime.close()
