"""Only an explicit, revision-bound user action closes the exact professional session."""

import asyncio

import pytest
from test_routing_policy import setup
from test_task_continuation_affinity import seed

from roami_agent.dispatch.task_sessions import TaskSessions
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row, rows


async def prepare(store):
    runtime, _, _, _, binding = await setup(store)
    task = await seed(runtime, binding, store.data_root)
    run = await store.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    calls = []

    class Executor:
        async def command(self, *args):
            calls.append(args)
            return {"state": "closed", "session": "original-session"}

    service = TaskSessions(store, Executor(), runtime.dispatch.confirm)
    return runtime, task, run, calls, service


async def test_explicit_close_accepts_waiting_result_and_preserves_history(store):
    runtime, task, run, calls, service = await prepare(store)
    try:
        assert not calls
        receipt = await service.close("alice", task["id"], 1, run["id"])
        assert receipt["state"] == "closed" and calls == [("close", "--key", run["launch_id"])]
        assert (await service.close("alice", task["id"], 1, run["id"])) == receipt and len(
            calls
        ) == 1
        detail = await runtime.tasks.get("alice", task["id"])
        assert (
            detail["sessionClosure"]["state"] == "closed" and detail["task"]["state"] == "succeeded"
        )
        assert detail["attempts"][0]["result"]["summary"] == "Design files exist"
        assert not await store.call(
            lambda db: rows(db, "SELECT id FROM turns WHERE trigger_kind='completion'")
        )
        with pytest.raises(DomainError, match="TASK_SESSION_CLOSED"):
            await runtime.tasks.revisions.request("alice", task["id"], "More work", 1, "later")
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "scenario,code",
    [
        ("foreign", "TASK_NOT_FOUND"),
        ("revision", "TASK_REVISION_CHANGED"),
        ("run", "TASK_REVISION_CHANGED"),
        ("busy", "TASK_SESSION_BUSY"),
        ("pending", "TASK_STEER_PENDING"),
    ],
)
async def test_stale_foreign_or_busy_close_never_reaches_cli(store, scenario, code):
    runtime, task, run, calls, service = await prepare(store)
    try:
        if scenario == "busy":
            await store.call(
                lambda db: db.execute("UPDATE tasks SET state='running' WHERE id=?", (task["id"],)),
                write=True,
            )
        if scenario == "pending":
            await runtime.tasks.revisions.request("alice", task["id"], "Continue", 1, "pending")
        with pytest.raises(DomainError, match=code):
            await service.close(
                "bob" if scenario == "foreign" else "alice",
                task["id"],
                2 if scenario == "revision" else 1,
                "wrong" if scenario == "run" else run["id"],
            )
        assert not calls
    finally:
        await runtime.close()


async def test_close_fences_a_racing_main_continuation(store):
    runtime, task, run, _, service = await prepare(store)
    entered, finish = asyncio.Event(), asyncio.Event()

    class Executor:
        async def command(self, *args):
            entered.set()
            await finish.wait()
            return {"state": "closed", "session": "original-session"}

    service.executor = Executor()
    try:
        closing = asyncio.create_task(service.close("alice", task["id"], 1, run["id"]))
        await entered.wait()
        with pytest.raises(DomainError, match="TASK_SESSION_CLOSING"):
            await runtime.tasks.revisions.request("alice", task["id"], "More work", 1, "race")
        finish.set()
        await closing
    finally:
        finish.set()
        await runtime.close()


@pytest.mark.parametrize("code", ["SESSION_NOT_IDLE", "TASK_SESSION_CLOSE_UNKNOWN"])
async def test_failed_or_unknown_close_is_not_reported_as_closed(store, code):
    runtime, task, run, _, service = await prepare(store)

    class Executor:
        async def command(self, *args):
            raise DomainError(code)

    service.executor = Executor()
    try:
        with pytest.raises(DomainError, match=code):
            await service.close("alice", task["id"], 1, run["id"])
        closure = (await runtime.tasks.get("alice", task["id"]))["sessionClosure"]
        assert closure["state"] == ("failed" if code == "SESSION_NOT_IDLE" else "unknown")
        assert (await runtime.tasks.get("alice", task["id"]))["task"]["state"] == "waiting_user"
    finally:
        await runtime.close()


async def test_unresolved_old_execution_cannot_be_closed_as_verified_completion(store):
    runtime, task, run, calls, service = await prepare(store)
    try:
        await store.call(
            lambda db: db.execute(
                "UPDATE task_attempts SET state='unknown',result_json='{\"outcomeKnown\":false}' WHERE id=?",
                (run["id"],),
            ),
            write=True,
        )
        with pytest.raises(DomainError, match="TASK_OUTCOME_UNRESOLVED"):
            await service.close("alice", task["id"], 1, run["id"])
        assert not calls
    finally:
        await runtime.close()


async def test_retry_after_acceptance_failure_does_not_close_the_professional_session_twice(store):
    runtime, task, run, calls, service = await prepare(store)
    original = service.confirm

    async def unavailable(*args, **kwargs):
        raise DomainError("INJECTED_ACCEPTANCE_FAILURE", 503)

    service.confirm = unavailable
    try:
        with pytest.raises(DomainError, match="INJECTED_ACCEPTANCE_FAILURE"):
            await service.close("alice", task["id"], 1, run["id"])
        assert len(calls) == 1
        service.confirm = original
        await service.close("alice", task["id"], 1, run["id"])
        assert len(calls) == 1
        assert (await runtime.tasks.get("alice", task["id"]))["task"]["state"] == "succeeded"
    finally:
        await runtime.close()
