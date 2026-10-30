"""A busy TUI defers submission; it has not failed the continued task."""

import asyncio
import json

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row, rows


@pytest.fixture
async def followup(store):
    settings = Settings(workers=1)
    executor = CodingExecutor(store, settings)
    runtime = Runtime(store, ConversationModel(), settings=settings, executor=executor)
    conversation = await runtime.conversations.create("alice")
    task = await runtime.tasks.create(
        "alice",
        conversation["id"],
        "Create a research page",
        key="initial",
        executor="claude",
        target={"kind": "session", "sessionId": "original-session"},
        record_intent=True,
    )
    old = await store.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    await store.call(
        lambda db: db.execute(
            "UPDATE task_attempts SET session_id='original-session' WHERE id=?", (old["id"],)
        ),
        write=True,
    )
    await runtime.tasks.report(
        "alice", task["id"], old["id"], 1, {"state": "succeeded", "summary": "Original page"}
    )
    await store.call(
        lambda db: db.execute("UPDATE jobs SET state='done' WHERE kind='task.run'"), write=True
    )
    verification = await store.call(
        lambda db: row(db, "SELECT * FROM jobs WHERE kind='task.verify'")
    )
    await runtime.dispatch.verify(verification)
    assert (await runtime.tasks.list("alice"))[0]["state"] == "waiting_user"
    await runtime.tasks.revisions.request("alice", task["id"], "Add more detail", 1, "append")
    await runtime.tasks.revisions.advance()
    try:
        yield runtime, executor, task, old
    finally:
        await runtime.close()


async def latest_job(store):
    return await store.call(
        lambda db: row(db, "SELECT * FROM jobs WHERE kind='task.run' ORDER BY rowid DESC LIMIT 1")
    )


@pytest.mark.parametrize("crash_during_retry", [False, True])
async def test_busy_followup_survives_restart_and_returns_only_its_own_result(
    store, followup, crash_during_retry
):
    runtime, executor, task, old = followup
    busy, launches = True, []

    async def command(sub, *args, spec=None):
        if sub == "launch":
            launches.append(spec)
            if busy:
                raise DomainError("SESSION_NOT_IDLE")
            return {"state": "running", "session": "original-session"}
        assert sub == "status"
        return {
            "state": "succeeded",
            "session": "original-session",
            "result": {"state": "succeeded", "summary": "Expanded research page"},
        }

    executor.command = command
    for _ in range(3):
        job = await latest_job(store)
        await runtime.scheduler._job(job)
        current = (await runtime.tasks.list("alice"))[0]
        assert current["revision"] == 2 and current["state"] == "queued"
        assert current["latestAttempt"]["state"] == "accepted"
        pending = await latest_job(store)
        assert pending["state"] == "queued" and pending["available_ms"] > now_ms()
        await executor.poll(runtime.tasks)
    if crash_during_retry:

        def interrupted(db):
            db.execute("UPDATE tasks SET state='preparing' WHERE id=?", (task["id"],))
            db.execute("UPDATE task_attempts SET state='starting' WHERE task_revision=2")
            db.execute("UPDATE jobs SET state='running' WHERE id=?", (pending["id"],))

        await store.call(interrupted, write=True)
    await runtime.dispatch.recover()
    assert (await latest_job(store))["state"] == "queued"
    assert (await runtime.tasks.list("alice"))[0]["state"] == "queued"
    busy = False
    await store.call(
        lambda db: db.execute("UPDATE jobs SET available_ms=0 WHERE id=?", (pending["id"],)),
        write=True,
    )
    await runtime.scheduler._scan()
    await asyncio.gather(*(job["handle"] for job in runtime.active.values()))
    assert (await latest_job(store))["state"] == "done"
    assert len({launch["key"] for launch in launches}) == 1
    assert all(launch["sessionId"] == "original-session" for launch in launches)
    assert all(launch["prompt"] == "Add more detail" for launch in launches)
    await executor.poll(runtime.tasks)
    verification = await store.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='task.verify' ORDER BY rowid DESC LIMIT 1"
        )
    )
    await runtime.dispatch.verify(verification)
    current = (await runtime.tasks.list("alice"))[0]
    assert current["state"] == "waiting_user"
    attempts = await store.call(
        lambda db: rows(
            db, "SELECT * FROM task_attempts WHERE task_id=? ORDER BY attempt_no", (task["id"],)
        )
    )
    assert len(attempts) == 2 and attempts[0]["id"] == old["id"]
    assert json.loads(attempts[0]["result_json"])["summary"] == "Original page"
    assert json.loads(attempts[1]["result_json"])["summary"] == "Expanded research page"
    budget = await store.call(
        lambda db: row(db, "SELECT budget_json FROM tasks WHERE id=?", (task["id"],))
    )
    assert json.loads(budget["budget_json"])["usedSteps"] == 1
    events = await runtime.conversations.events("alice", task["origin_conversation_id"])
    assert not any(event["kind"] == "task.failed" for event in events)
    assert sum(event["kind"] == "task.preparing" for event in events) == 1


@pytest.mark.parametrize("cancel_during_launch", [False, True])
async def test_cancellation_stops_a_pending_followup_without_sending(
    store, followup, cancel_during_launch
):
    runtime, executor, task, _old = followup
    launches = 0

    async def command(sub, *args, **kwargs):
        nonlocal launches
        assert sub == "launch"
        launches += 1
        if cancel_during_launch:
            await runtime.tasks.cancel("alice", task["id"])
        raise DomainError("SESSION_NOT_IDLE")

    executor.command = command
    await runtime.scheduler._job(await latest_job(store))
    if not cancel_during_launch:
        await runtime.tasks.cancel("alice", task["id"])
    await runtime.dispatch.cancel()
    verification = await store.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='task.verify' ORDER BY rowid DESC LIMIT 1"
        )
    )
    await runtime.dispatch.verify(verification)
    await runtime.scheduler._job(await latest_job(store))
    assert launches == 1
    assert (await runtime.tasks.list("alice"))[0]["state"] == "cancelled"


async def test_uncertain_submission_is_observed_instead_of_retried(store, followup):
    runtime, executor, _task, _old = followup
    calls = []

    async def command(sub, *args, **kwargs):
        calls.append(sub)
        if sub == "launch":
            raise DomainError("SESSION_SUBMISSION_UNKNOWN")
        return {"state": "unknown"}

    executor.command = command
    await runtime.scheduler._job(await latest_job(store))
    await executor.poll(runtime.tasks)
    await executor.poll(runtime.tasks)
    assert calls == ["launch", "status", "status"]
    assert (await latest_job(store))["state"] == "done"
    assert (await runtime.tasks.list("alice"))[0]["latestAttempt"]["state"] == "unknown"


@pytest.mark.parametrize(
    "code",
    ["SESSION_DIRECTORY_CHANGED", "SESSION_TARGET_NOT_FOUND", "SESSION_LIFECYCLE_UNAVAILABLE"],
)
async def test_permanent_session_rejection_is_not_retried(store, followup, code):
    runtime, executor, _task, _old = followup

    async def command(sub, *args, **kwargs):
        assert sub == "launch"
        raise DomainError(code)

    executor.command = command
    await runtime.scheduler._job(await latest_job(store))
    verification = await store.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='task.verify' ORDER BY rowid DESC LIMIT 1"
        )
    )
    await runtime.dispatch.verify(verification)
    current = (await runtime.tasks.list("alice"))[0]
    assert current["state"] == "failed" and current["latestAttempt"]["summary"] == code
    assert (await latest_job(store))["state"] == "done"
