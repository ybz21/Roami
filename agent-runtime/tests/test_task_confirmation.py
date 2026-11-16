"""Accepting a reported result updates task state without repeating the answer."""

import json

import pytest
from test_task_cancellation import QuietModel, task_run, verification

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import rows


@pytest.mark.parametrize("accepted", [True, False])
async def test_acceptance_keeps_first_report_without_another_completion_turn(store, accepted):
    async def requires_acceptance(task, result):
        return False

    runtime = Runtime(store, QuietModel(), verifier=requires_acceptance)
    try:
        conversation = await runtime.conversations.create("alice")
        task, run = await task_run(runtime, conversation, "process-usage")
        evidence = {"state": "succeeded", "summary": "The machine is lightly loaded."}
        await runtime.tasks.report("alice", task["id"], run["id"], 1, evidence)
        await runtime.dispatch.verify(await verification(runtime, task))
        before = await store.call(
            lambda db: rows(db, "SELECT * FROM turns WHERE trigger_kind='completion'")
        )
        assert len(before) == 1
        receipt = await runtime.dispatch.confirm(
            "alice", task["id"], accepted, revision=1, run_id=run["id"]
        )
        expected = "succeeded" if accepted else "failed"
        assert receipt == {"taskId": task["id"], "state": expected}
        after = await store.call(
            lambda db: rows(db, "SELECT * FROM turns WHERE trigger_kind='completion'")
        )
        assert len(after) == (1 if accepted else 2)
        assert before[0] in after
        detail = await runtime.tasks.get("alice", task["id"])
        assert detail["task"]["state"] == expected
        assert detail["attempts"][0]["result"] == evidence
        events = await store.call(
            lambda db: rows(
                db,
                "SELECT * FROM events WHERE task_id=? AND kind=?",
                (task["id"], "task." + expected),
            )
        )
        assert len(events) == 1
        assert json.loads(events[0]["payload_json"])["state"] == expected
        with pytest.raises(DomainError, match="TASK_NOT_WAITING_VERIFICATION"):
            await runtime.dispatch.confirm("alice", task["id"], accepted)
    finally:
        await runtime.close()


@pytest.mark.parametrize("stopped", [True, False])
async def test_unconfirmed_acceptance_reconciles_bound_execution_before_accepting(store, stopped):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from roami_agent.executors.roami_cli import CodingExecutor

    executor = CodingExecutor(store, SimpleNamespace())
    known = {
        "state": "succeeded",
        "summary": "Reviewed report",
        "inputStopped": stopped,
        "outcomeKnown": stopped,
    }
    executor.command = AsyncMock(side_effect=[{"state": "unknown"}, {"result": known}])
    runtime = Runtime(store, QuietModel(), executor=executor)
    try:
        conversation = await runtime.conversations.create("alice")
        task, run = await task_run(runtime, conversation, "unconfirmed-result")
        await store.call(
            lambda db: db.execute(
                "UPDATE task_attempts SET executor_kind='cli',state='unknown' WHERE id=?",
                (run["id"],),
            ),
            write=True,
        )
        if stopped:
            receipt = await runtime.dispatch.confirm(
                "alice", task["id"], True, revision=1, run_id=run["id"]
            )
            assert receipt["state"] == "succeeded"
        else:
            with pytest.raises(DomainError, match="TASK_STOP_UNCONFIRMED"):
                await runtime.dispatch.confirm(
                    "alice", task["id"], True, revision=1, run_id=run["id"]
                )
            detail = await runtime.tasks.get("alice", task["id"])
            assert detail["task"]["state"] == "running"
            assert detail["attempts"][0]["result"] is None
        assert executor.command.call_args_list[0].args == ("status", "--key", run["launch_id"])
        assert executor.command.call_args_list[1].args == (
            "reconcile-session",
            "--key",
            run["launch_id"],
        )
    finally:
        await runtime.close()


async def test_stale_confirmation_cannot_reconcile_an_execution(store):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    executor = SimpleNamespace(can_reconcile=True, command=AsyncMock())
    runtime = Runtime(store, QuietModel(), executor=executor)
    try:
        conversation = await runtime.conversations.create("alice")
        task, run = await task_run(runtime, conversation, "stale-confirmation")
        await store.call(
            lambda db: db.execute(
                "UPDATE task_attempts SET executor_kind='cli',state='unknown' WHERE id=?",
                (run["id"],),
            ),
            write=True,
        )
        for revision, run_id, code in [
            (2, run["id"], "TASK_REVISION_CHANGED"),
            (1, "old", "TASK_RESULT_SUPERSEDED"),
        ]:
            with pytest.raises(DomainError, match=code):
                await runtime.dispatch.confirm(
                    "alice", task["id"], True, revision=revision, run_id=run_id
                )
        executor.command.assert_not_called()
    finally:
        await runtime.close()


async def test_confirmation_waits_for_the_scheduled_verifier_instead_of_running_it_twice(store):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from roami_agent.executors.roami_cli import CodingExecutor

    executor = CodingExecutor(store, SimpleNamespace())
    executor.command = AsyncMock(
        return_value={
            "result": {
                "state": "succeeded",
                "summary": "Reviewed report",
                "inputStopped": True,
                "outcomeKnown": True,
            }
        }
    )
    verifier = AsyncMock(return_value=False)
    runtime = Runtime(store, QuietModel(), executor=executor, verifier=verifier)
    try:
        conversation = await runtime.conversations.create("alice")
        task, run = await task_run(runtime, conversation, "scheduled-confirmation")
        await store.call(
            lambda db: db.execute(
                "UPDATE task_attempts SET executor_kind='cli',state='unknown' WHERE id=?",
                (run["id"],),
            ),
            write=True,
        )
        original = runtime.tasks.report

        async def report_then_schedule(*args, **kwargs):
            result = await original(*args, **kwargs)
            await runtime.scheduler._scan()
            return result

        runtime.tasks.report = report_then_schedule
        receipt = await runtime.dispatch.confirm(
            "alice", task["id"], True, revision=1, run_id=run["id"]
        )
        assert receipt["state"] == "succeeded"
        verifier.assert_awaited_once()
    finally:
        await runtime.close()
