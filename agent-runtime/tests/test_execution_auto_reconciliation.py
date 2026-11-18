import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from test_task_cancellation import QuietModel, verification

from roami_agent.app import Runtime
from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


@pytest.fixture
async def monitored(store, mock_executor_catalog, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("roami_agent.executors.roami_cli.monotonic", lambda: clock[0])
    executor = CodingExecutor(store, Settings())
    runtime = Runtime(
        store, QuietModel(), executor=executor, verifier=AsyncMock(return_value=False)
    )
    conversation = await runtime.conversations.create("alice")

    async def create(key="auto-check"):
        task = await runtime.tasks.create(
            "alice", conversation["id"], key, key=key, executor="codex", record_intent=True
        )

        def launched(db):
            db.execute("UPDATE tasks SET state='running' WHERE id=?", (task["id"],))
            db.execute(
                "UPDATE task_attempts SET state='unknown',session_id='work' WHERE task_id=?",
                (task["id"],),
            )
            db.execute("UPDATE jobs SET state='done' WHERE aggregate_id=?", (task["id"],))
            return row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))

        return task, await store.call(launched, write=True)

    try:
        yield runtime, executor, clock, create, conversation
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    ("initial", "terminal", "expected"),
    [
        ("preparing", "succeeded", "waiting_user"),
        ("running", "succeeded", "waiting_user"),
        ("running", "failed", "failed"),
        ("cancelling", "succeeded", "cancelled"),
        ("cancelling", "cancelled", "cancelled"),
        ("interrupted", "succeeded", "interrupted"),
    ],
)
async def test_background_check_without_a_report_never_submits_acceptance(
    monitored, initial, terminal, expected
):
    runtime, executor, _clock, create, _ = monitored
    task, run = await create()

    def state(db):
        db.execute("UPDATE tasks SET state=? WHERE id=?", (initial, task["id"]))
        if initial == "interrupted":
            db.execute(
                "UPDATE task_attempts SET result_json=? WHERE id=?",
                (json.dumps({"state": "failed", "outcomeKnown": False}), run["id"]),
            )

    await runtime.db.call(state, write=True)
    calls = []
    result = {
        "state": terminal,
        "summary": "Retained report",
        "inputStopped": True,
        "outcomeKnown": True,
    }

    async def command(sub, *args):
        calls.append((sub, *args))
        return {"result": result} if sub == "reconcile-session" else {"state": "unknown"}

    executor.command = command
    await executor.poll(runtime.tasks)
    job = await verification(runtime, task)
    if job:
        await runtime.dispatch.verify(job)
    detail = await runtime.tasks.get("alice", task["id"])
    assert detail["task"]["state"] == expected
    assert detail["attempts"][0]["result"]["inputStopped"] is True
    assert detail["attempts"][0]["result"]["outcomeKnown"] is True
    expected_commands = (["cancel"] if initial == "cancelling" else []) + [
        "status",
        "reconcile-session",
    ]
    assert [call[0] for call in calls] == expected_commands
    assert all(call[1:] == ("--key", run["launch_id"]) for call in calls)
    before = len(calls)
    await executor.poll(runtime.tasks)
    assert len(calls) == before


async def test_unknown_evidence_backs_off_without_flipping_observation_reason(monitored):
    runtime, executor, clock, create, conversation = monitored
    task, _ = await create()
    checks = []
    observation = {"state": "unknown", "observationErrorCode": "SESSION_COMPLETION_MISMATCH"}

    async def command(sub, *args):
        if sub == "reconcile-session":
            checks.append(clock[0])
            raise DomainError("CODING_EXECUTOR_UNAVAILABLE")
        return observation

    executor.command = command
    for stamp in [100, 101, 104, 105, 114, 115, 135, 175, 235, 295]:
        clock[0] = stamp
        await executor.poll(runtime.tasks)
    assert checks == [100, 105, 115, 135, 175, 235, 295]
    detail = await runtime.tasks.get("alice", task["id"])
    assert detail["task"]["state"] == "running"
    assert detail["attempts"][0]["result"] is None
    events = await runtime.conversations.events("alice", conversation["id"])
    unknown = [event for event in events if event["kind"] == "task.observation_unknown"]
    assert len(unknown) == 1
    assert unknown[0]["payload"]["errorCode"] == "SESSION_COMPLETION_MISMATCH"
    clock[0] = 296
    observation = {"state": "running", "session": "work"}
    await executor.poll(runtime.tasks)
    assert not executor._reconciliation_retries
    clock[0] = 297
    observation = {"state": "unknown"}
    await executor.poll(runtime.tasks)
    assert checks[-1] == 297


@pytest.mark.parametrize("field", ["inputStopped", "outcomeKnown"])
@pytest.mark.parametrize("value", [None, False])
async def test_automatic_reconciliation_requires_both_explicit_stop_flags(monitored, field, value):
    runtime, executor, _, create, _ = monitored
    task, _ = await create()
    result = {"state": "succeeded", "inputStopped": True, "outcomeKnown": True}
    if value is None:
        result.pop(field)
    else:
        result[field] = value

    async def command(sub, *args):
        return {"result": result} if sub == "reconcile-session" else {"state": "unknown"}

    executor.command = command
    await executor.poll(runtime.tasks)
    detail = await runtime.tasks.get("alice", task["id"])
    assert detail["task"]["state"] == "running"
    assert detail["attempts"][0]["result"] is None
    assert await verification(runtime, task) is None


async def test_reconciliation_budget_is_bounded_and_old_entries_are_removed(monitored):
    runtime, executor, clock, create, _ = monitored
    tasks = [await create(str(index)) for index in range(5)]
    checked = []

    async def command(sub, *args):
        if sub == "reconcile-session":
            checked.append(args[-1])
        return {"state": "unknown"}

    executor.command = command
    for stamp, total in [(100, 2), (101, 4), (102, 5)]:
        clock[0] = stamp
        await executor.poll(runtime.tasks)
        assert len(checked) == total
    assert set(checked) == {run["launch_id"] for _, run in tasks}
    await runtime.db.call(
        lambda db: db.execute("UPDATE tasks SET state='waiting_user'"), write=True
    )
    await executor.poll(runtime.tasks)
    assert not executor._reconciliation_retries


@pytest.mark.parametrize("phase", ["status", "reconcile-session"])
@pytest.mark.parametrize("change", ["revision", "attempt", "terminal"])
async def test_automatic_check_does_not_advance_a_replaced_or_ended_run(monitored, phase, change):
    runtime, executor, _, create, _ = monitored
    task, run = await create()
    calls = []

    def replace(db):
        if change == "revision":
            db.execute("UPDATE tasks SET revision=2,state='queued' WHERE id=?", (task["id"],))
        elif change == "terminal":
            db.execute("UPDATE tasks SET state='cancelled' WHERE id=?", (task["id"],))
        else:
            newer = {**run, "id": "newer-run", "launch_id": "newer-launch", "attempt_no": 2}
            columns = ",".join(newer)
            values = ",".join("?" for _ in newer)
            db.execute(
                f"INSERT INTO task_attempts({columns}) VALUES({values})", tuple(newer.values())
            )

    async def command(sub, *args):
        calls.append(sub)
        if sub == phase:
            await runtime.db.call(replace, write=True)
        return (
            {"result": {"state": "succeeded", "inputStopped": True, "outcomeKnown": True}}
            if sub == "reconcile-session"
            else {"state": "unknown"}
        )

    executor.command = command
    await executor.poll(runtime.tasks)
    detail = await runtime.tasks.get("alice", task["id"])
    assert (
        detail["task"]["state"]
        == {"revision": "queued", "terminal": "cancelled", "attempt": "running"}[change]
    )
    assert calls == (["status"] if phase == "status" else ["status", "reconcile-session"])
    assert await verification(runtime, task) is None
    assert all(attempt["result"] is None for attempt in detail["attempts"])


async def test_old_attempt_is_not_polled_and_a_new_monitor_rechecks_pending_evidence(monitored):
    runtime, executor, _, create, _ = monitored
    _task, run = await create()
    calls = []

    async def command(sub, *args):
        calls.append((sub, args[-1]))
        return {"state": "unknown"}

    executor.command = command
    await executor.poll(runtime.tasks)
    restarted = CodingExecutor(runtime.db, Settings())
    restarted.command = command
    await restarted.poll(runtime.tasks)
    assert [sub for sub, _ in calls].count("reconcile-session") == 2

    def newer(db):
        replacement = {**run, "id": "newer-run", "launch_id": "newer-launch", "attempt_no": 2}
        columns = ",".join(replacement)
        values = ",".join("?" for _ in replacement)
        db.execute(
            f"INSERT INTO task_attempts({columns}) VALUES({values})", tuple(replacement.values())
        )

    await runtime.db.call(newer, write=True)
    calls.clear()
    await restarted.poll(runtime.tasks)
    assert calls == [("status", "newer-launch"), ("reconcile-session", "newer-launch")]


@pytest.mark.parametrize("state", ["running", "unknown"])
async def test_running_or_unsupported_executions_do_not_get_extra_checks(monitored, state):
    runtime, executor, _, create, _ = monitored
    task, _ = await create()
    if state == "unknown":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE tasks SET intent_json=json_set(intent_json,'$.executor','opencode') WHERE id=?",
                (task["id"],),
            ),
            write=True,
        )
    executor.command = AsyncMock(return_value={"state": state})
    await executor.poll(runtime.tasks)
    assert [call.args[0] for call in executor.command.call_args_list] == ["status"]


async def test_slow_failed_check_waits_after_completion_before_retrying(monitored):
    runtime, executor, clock, create, _ = monitored
    await create()
    checks = []

    async def command(sub, *args):
        if sub == "reconcile-session":
            checks.append(clock[0])
            clock[0] += 15
            raise TimeoutError
        return {"state": "unknown"}

    executor.command = command
    await executor.poll(runtime.tasks)
    clock[0] = 116
    await executor.poll(runtime.tasks)
    assert checks == [100]
    clock[0] = 120
    await executor.poll(runtime.tasks)
    assert checks == [100, 120]


async def test_background_monitor_reconciles_and_wakes_verification_without_ui_requests(monitored):
    runtime, executor, _, create, _ = monitored
    task, _ = await create()
    calls = []

    async def command(sub, *args):
        calls.append(sub)
        return (
            {"result": {"state": "succeeded", "inputStopped": True, "outcomeKnown": True}}
            if sub == "reconcile-session"
            else {"state": "unknown"}
        )

    executor.command = command
    runtime.wakeup.clear()
    monitor = asyncio.create_task(runtime._monitor_external())
    try:
        async with asyncio.timeout(5):
            while not runtime.wakeup.is_set():
                await asyncio.sleep(0.01)
        detail = await runtime.tasks.get("alice", task["id"])
        assert detail["task"]["state"] == "verifying"
        assert calls == ["status", "reconcile-session"]
        await runtime.dispatch.verify(await verification(runtime, task))
        detail = await runtime.tasks.get("alice", task["id"])
        assert detail["task"]["state"] == "waiting_user"
    finally:
        monitor.cancel()
        await asyncio.gather(monitor, return_exceptions=True)
