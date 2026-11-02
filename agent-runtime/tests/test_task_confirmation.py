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
