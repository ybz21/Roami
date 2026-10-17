"""Cancellation remains authoritative while execution and verification finish."""

import asyncio
import json

import pytest

from roami_agent.app import Runtime
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.database import row, rows


class QuietModel:
    model = "cancellation-fixture"

    async def stream(self, messages, tools):
        yield ModelEvent("text", "Task update received")


async def task_run(runtime, conversation, key, parent=None):
    task = await runtime.tasks.create(
        "alice",
        conversation["id"],
        key,
        key=key,
        parent_task_id=parent,
        record_intent=True,
    )
    await runtime.db.call(
        lambda db: db.execute("UPDATE tasks SET state='running' WHERE id=?", (task["id"],)),
        write=True,
    )
    run = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    return task, run


async def verification(runtime, task):
    return await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='task.verify' AND aggregate_id=?", (task["id"],)
        )
    )


async def state(runtime, task):
    return (
        await runtime.db.call(
            lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],))
        )
    )["state"]


@pytest.mark.parametrize("reported", ["succeeded", "failed", "cancelled"])
async def test_cancel_intent_survives_a_late_result_and_has_one_completion(store, reported):
    runtime = Runtime(store, QuietModel())
    try:
        conversation = await runtime.conversations.create("alice")
        task, run = await task_run(runtime, conversation, "late-result")
        await runtime.tasks.cancel("alice", task["id"])
        evidence = {"state": reported, "summary": "Actual executor result"}
        response = await runtime.tasks.report("alice", task["id"], run["id"], 1, evidence)
        assert response["state"] == "cancelling"
        job = await verification(runtime, task)
        await runtime.dispatch.verify(job)
        await runtime.dispatch.verify(job)
        assert await state(runtime, task) == "cancelled"
        saved = await store.call(
            lambda db: row(db, "SELECT result_json FROM task_attempts WHERE id=?", (run["id"],))
        )
        assert json.loads(saved["result_json"]) == evidence
        completion = await store.call(
            lambda db: rows(
                db, "SELECT * FROM events WHERE task_id=? AND kind='task.cancelled'", (task["id"],)
            )
        )
        assert len(completion) == 1
        assert json.loads(completion[0]["payload_json"])["result"]["cancellationRequested"]
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "child_state, expected", [("cancelled", "cancelled"), ("interrupted", "interrupted")]
)
async def test_cancelled_parent_waits_for_child_stop_and_preserves_unknown_child(
    store, child_state, expected
):
    runtime = Runtime(store, QuietModel())
    try:
        conversation = await runtime.conversations.create("alice")
        parent, parent_run = await task_run(runtime, conversation, "parent")
        child, child_run = await task_run(runtime, conversation, "child", parent["id"])
        await runtime.tasks.cancel("alice", parent["id"])
        await runtime.tasks.report(
            "alice", parent["id"], parent_run["id"], 1, {"state": "cancelled"}
        )
        parent_job = await verification(runtime, parent)
        await runtime.dispatch.verify(parent_job)
        assert await state(runtime, parent) == "cancelling"
        assert await state(runtime, child) == "cancelling"
        if child_state == "cancelled":
            await runtime.tasks.report(
                "alice", child["id"], child_run["id"], 1, {"state": "cancelled"}
            )
            await runtime.dispatch.verify(await verification(runtime, child))
        else:
            await runtime.dispatch.complete(
                child,
                child_run,
                {"state": "failed", "outcomeKnown": False},
                "interrupted",
                unknown=True,
            )
        await runtime.dispatch.verify(parent_job)
        assert await state(runtime, parent) == expected
        completion = await store.call(
            lambda db: row(
                db,
                "SELECT payload_json FROM events WHERE task_id=? AND kind=?",
                (parent["id"], "task." + expected),
            )
        )
        assert json.loads(completion["payload_json"])["result"]["inputStopped"] is (
            child_state == "cancelled"
        )
    finally:
        await runtime.close()


async def test_cancel_during_verifier_cannot_be_overwritten_by_success(store):
    entered, release = asyncio.Event(), asyncio.Event()

    async def verifier(task, result):
        entered.set()
        await release.wait()
        return True

    runtime = Runtime(store, QuietModel(), verifier=verifier)
    try:
        conversation = await runtime.conversations.create("alice")
        task, run = await task_run(runtime, conversation, "verify-race")
        await runtime.tasks.report("alice", task["id"], run["id"], 1, {"state": "succeeded"})
        verify = asyncio.create_task(runtime.dispatch.verify(await verification(runtime, task)))
        await asyncio.wait_for(entered.wait(), 2)
        await runtime.tasks.cancel("alice", task["id"])
        release.set()
        await verify
        assert await state(runtime, task) == "cancelled"
    finally:
        release.set()
        await runtime.close()


async def test_waiting_for_acceptance_can_cancel_after_verification_job_finished(store):
    async def rejected(task, result):
        return False

    runtime = Runtime(store, QuietModel(), verifier=rejected)
    try:
        conversation = await runtime.conversations.create("alice")
        task, run = await task_run(runtime, conversation, "waiting-acceptance")
        await runtime.tasks.report("alice", task["id"], run["id"], 1, {"state": "succeeded"})
        await runtime.dispatch.verify(await verification(runtime, task))
        assert await state(runtime, task) == "waiting_user"
        assert (await verification(runtime, task))["state"] == "done"
        await runtime.tasks.cancel("alice", task["id"])
        assert (await verification(runtime, task))["state"] == "queued"
        await runtime.dispatch.verify(await verification(runtime, task))
        assert await state(runtime, task) == "cancelled"
    finally:
        await runtime.close()


async def test_cancel_with_unknown_own_stop_never_claims_confirmed_cancelled(store):
    runtime = Runtime(store, QuietModel())
    try:
        conversation = await runtime.conversations.create("alice")
        task, run = await task_run(runtime, conversation, "unknown-stop")
        await runtime.tasks.cancel("alice", task["id"])
        await runtime.tasks.report(
            "alice", task["id"], run["id"], 1, {"state": "failed", "outcomeKnown": False}
        )
        await runtime.dispatch.verify(await verification(runtime, task))
        assert await state(runtime, task) == "interrupted"
    finally:
        await runtime.close()
