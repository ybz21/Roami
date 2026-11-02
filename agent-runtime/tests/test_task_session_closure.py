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


async def close_job(store, task_id):
    return await store.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='task.close_session' AND aggregate_id=?", (task_id,)
        )
    )


async def test_queued_close_survives_a_new_service_and_fences_continuations(store):
    runtime, task, run, calls, service = await prepare(store)
    try:
        first = await service.request("alice", task["id"], 1, run["id"])
        assert first["state"] == "closing"
        assert await service.request("alice", task["id"], 1, run["id"]) == first
        assert not calls
        with pytest.raises(DomainError, match="TASK_SESSION_CLOSING"):
            await runtime.tasks.revisions.request("alice", task["id"], "racing edit", 1, "racing")
        recovered = TaskSessions(store, service.executor, runtime.dispatch.confirm)
        await recovered.advance(await close_job(store, task["id"]))
        detail = await runtime.tasks.get("alice", task["id"])
        assert detail["sessionClosure"]["state"] == "closed"
        assert detail["task"]["state"] == "succeeded"
        assert len(calls) == 1
        assert (await close_job(store, task["id"]))["state"] == "done"
    finally:
        await runtime.close()


async def test_cleanup_failure_is_visible_and_retry_keeps_the_exact_run(store):
    runtime, task, run, _calls, service = await prepare(store)
    cleaned = []

    async def cleanup(task, run):
        cleaned.append(run["id"])
        if len(cleaned) == 1:
            raise DomainError("WORKTREE_DIRTY", 409)

    service.cleanup = cleanup
    try:
        await service.request("alice", task["id"], 1, run["id"])
        await service.advance(await close_job(store, task["id"]))
        detail = await runtime.tasks.get("alice", task["id"])
        assert detail["sessionClosure"]["state"] == "failed"
        assert detail["sessionClosure"]["error_code"] == "WORKTREE_DIRTY"
        assert detail["task"]["state"] == "waiting_user"
        await service.request("alice", task["id"], 1, run["id"])
        await service.advance(await close_job(store, task["id"]))
        assert (await runtime.tasks.get("alice", task["id"]))["sessionClosure"]["state"] == "closed"
        assert cleaned == [run["id"], run["id"]]
    finally:
        await runtime.close()


@pytest.mark.parametrize("queued_follower", [False, True])
async def test_one_close_request_stops_an_active_native_task_and_closes_automatically(
    store, queued_follower
):
    from roami_agent.app import Runtime
    from roami_agent.protocol.models import ModelEvent
    from roami_agent.server.configuration import Settings

    entered = asyncio.Event()

    class Model:
        model = "close-fixture"

        async def stream(self, messages, tools):
            entered.set()
            await asyncio.Event().wait()
            yield ModelEvent("text", "unused")

    runtime = Runtime(store, Model(), settings=Settings(workers=1))
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", conversation["id"], "Do work", key="active-close", record_intent=True
        )
        await runtime.start()
        await asyncio.wait_for(entered.wait(), 3)
        if queued_follower:
            await runtime.tasks.create(
                "alice", conversation["id"], "Other work", key="follower", record_intent=True
            )
        run = await store.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
        )
        response = await runtime.task_sessions.request("alice", task["id"], 1, run["id"])
        assert response["state"] == "closing"
        runtime.wakeup.set()
        async with asyncio.timeout(5):
            while True:
                detail = await runtime.tasks.get("alice", task["id"])
                if detail["sessionClosure"]["state"] == "closed":
                    break
                assert detail["sessionClosure"]["state"] != "failed", detail
                await asyncio.sleep(0.03)
        assert detail["task"]["state"] == "cancelled"
        assert (await close_job(store, task["id"]))["state"] == "done"
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "scenario,code",
    [
        ("foreign", "TASK_NOT_FOUND"),
        ("revision", "TASK_REVISION_CHANGED"),
        ("run", "TASK_REVISION_CHANGED"),
    ],
)
async def test_close_request_validates_owner_revision_and_attempt_before_queuing(
    store, scenario, code
):
    runtime, task, run, calls, service = await prepare(store)
    try:
        with pytest.raises(DomainError, match=code):
            await service.request(
                "bob" if scenario == "foreign" else "alice",
                task["id"],
                2 if scenario == "revision" else 1,
                "wrong" if scenario == "run" else run["id"],
            )
        assert not calls
        assert await close_job(store, task["id"]) is None
        assert (await runtime.tasks.get("alice", task["id"]))["sessionClosure"] is None
    finally:
        await runtime.close()


async def test_close_request_finishes_waiting_child_sessions_before_the_parent(store):
    runtime, task, run, _calls, service = await prepare(store)
    try:
        await store.call(
            lambda db: db.execute("UPDATE tasks SET state='running' WHERE id=?", (task["id"],)),
            write=True,
        )
        child = await runtime.tasks.create(
            "alice",
            task["origin_conversation_id"],
            "Child work",
            key="close-child",
            parent_task_id=task["id"],
            record_intent=True,
        )
        await store.call(
            lambda db: db.execute(
                "UPDATE tasks SET state='waiting_user' WHERE id IN (?,?)", (task["id"], child["id"])
            ),
            write=True,
        )
        await store.call(
            lambda db: db.execute(
                "UPDATE task_attempts SET state='succeeded',finished_ms=1,result_json='{}' WHERE task_id=?",
                (child["id"],),
            ),
            write=True,
        )
        await service.request("alice", task["id"], 1, run["id"])
        with pytest.raises(DomainError, match="TASK_SESSION_CLOSING"):
            await runtime.tasks.revisions.request(
                "alice", child["id"], "Racing child continuation", 1, "child-race"
            )
        await service.advance(await close_job(store, task["id"]))
        for ident in (child["id"], task["id"]):
            detail = await runtime.tasks.get("alice", ident)
            assert detail["sessionClosure"]["state"] == "closed"
            assert detail["task"]["state"] == "succeeded"
    finally:
        await runtime.close()
