"""Execution identities survive review without making a new execution result."""

import hashlib
import json
import sqlite3

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row, rows
from roami_agent.storage.task_result_receipts import KIND, receipt_for_run, record_execution_result


@pytest.fixture
async def execution(store):
    runtime = Runtime(store, ConversationModel())
    c = await runtime.conversations.create("alice")
    await runtime.conversations.accept("alice", c["id"], "origin", "Produce a reviewable file")
    task = await runtime.tasks.create(
        "alice", c["id"], "Produce a reviewable file", key="result", executor="codex"
    )
    run = await store.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    yield runtime, task, run
    await runtime.close()


async def facts(store, task):
    return await store.call(
        lambda db: rows(
            db, "SELECT * FROM events WHERE task_id=? AND kind=? ORDER BY id", (task["id"], KIND)
        )
    )


async def test_duplicate_report_has_one_host_identity_without_repeating_result_body(
    execution, store
):
    runtime, task, run = execution
    result = {"state": "succeeded", "summary": "Actual source evidence", "inputStopped": True}
    for _ in range(2):
        await runtime.tasks.report("alice", task["id"], run["id"], 1, result)
    events = await facts(store, task)
    assert len(events) == 1 and "Actual source evidence" not in events[0]["payload_json"]
    receipt = (await runtime.tasks.get("alice", task["id"]))["task"]["latestAttempt"][
        "executionReceipt"
    ]
    assert receipt["receiptId"] == events[0]["id"]
    assert receipt["resultSha256"] == hashlib.sha256(encoded(result).encode()).hexdigest()
    assert receipt["source"] == "host_execution_result" and "accepted" not in receipt
    assert receipt["taskRevision"] == 1 and receipt["runId"] == run["id"]
    with pytest.raises(DomainError, match="TASK_NOT_FOUND"):
        await runtime.tasks.get("bob", task["id"])


async def test_main_confirmation_reuses_original_execution_receipt(execution, store):
    runtime, task, run = execution
    result = {"state": "succeeded", "summary": "Needs independent review", "inputStopped": True}
    await runtime.tasks.report("alice", task["id"], run["id"], 1, result)
    task = await store.call(lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],)))
    run = await store.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE id=?", (run["id"],))
    )
    await runtime.dispatch.complete(task, run, result, "waiting_user")
    before = await facts(store, task)
    queued = await store.call(
        lambda db: db.execute("SELECT count(*) FROM jobs WHERE kind='turn.run'").fetchone()[0]
    )
    await runtime.dispatch.confirm("alice", task["id"], True, revision=1, run_id=run["id"])
    assert await facts(store, task) == before
    assert (
        await store.call(
            lambda db: db.execute("SELECT count(*) FROM jobs WHERE kind='turn.run'").fetchone()[0]
        )
        == queued
    )
    completed = await store.call(
        lambda db: rows(
            db,
            "SELECT payload_json FROM events WHERE task_id=? AND kind IN ('task.waiting_user','task.succeeded')",
            (task["id"],),
        )
    )
    assert len(completed) == 2
    assert all(
        json.loads(e["payload_json"])["executionReceipt"]["receiptId"] == before[0]["id"]
        for e in completed
    )


async def test_legacy_confirmation_does_not_backfill_automatic_result_authority(execution, store):
    runtime, task, run = execution
    result = {"state": "succeeded", "summary": "Pre-upgrade result"}
    await store.call(
        lambda db: db.execute(
            "UPDATE task_attempts SET state='succeeded',result_json=? WHERE id=?",
            (encoded(result), run["id"]),
        ),
        write=True,
    )
    await runtime.dispatch.complete(task, run, result, "waiting_user")
    await runtime.dispatch.confirm("alice", task["id"], True, revision=1, run_id=run["id"])
    assert not await facts(store, task)
    assert (
        "executionReceipt"
        not in (await runtime.tasks.get("alice", task["id"]))["task"]["latestAttempt"]
    )


async def test_unknown_reconciliation_keeps_two_execution_facts(execution, store):
    runtime, task, run = execution
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='running' WHERE id=?", (task["id"],)),
        write=True,
    )
    unknown = {
        "state": "failed",
        "summary": "Outcome unknown",
        "outcomeKnown": False,
        "inputStopped": False,
    }
    await runtime.dispatch.complete(task, run, unknown, "interrupted", unknown=True)
    before = await facts(store, task)
    assert len(before) == 1 and json.loads(before[0]["payload_json"])["outcomeKnown"] is False
    result = {
        "state": "succeeded",
        "summary": "Reconciled actual result",
        "outcomeKnown": True,
        "inputStopped": True,
    }
    await runtime.tasks.report("alice", task["id"], run["id"], 1, result)
    after = await facts(store, task)
    assert len(after) == 2 and after[0] == before[0]
    current = await store.call(lambda db: receipt_for_run(db, task["id"], run["id"]))
    assert current["receiptId"] == after[1]["id"] and current["outcomeKnown"] is True


async def test_failed_receipt_insert_rolls_back_result_and_verification_job(execution, store):
    runtime, task, run = execution
    await store.call(
        lambda db: db.execute(
            "CREATE TRIGGER reject_result_fact BEFORE INSERT ON events WHEN NEW.kind='task.execution_result_recorded' BEGIN SELECT RAISE(ABORT,'fixture failure'); END"
        ),
        write=True,
    )
    with pytest.raises(sqlite3.IntegrityError, match="fixture failure"):
        await runtime.tasks.report(
            "alice", task["id"], run["id"], 1, {"state": "succeeded", "summary": "Atomic result"}
        )
    current = await store.call(
        lambda db: row(db, "SELECT result_json FROM task_attempts WHERE id=?", (run["id"],))
    )
    assert current["result_json"] is None and not await facts(store, task)
    assert not await store.call(
        lambda db: row(
            db, "SELECT id FROM jobs WHERE kind='task.verify' AND aggregate_id=?", (task["id"],)
        )
    )


async def test_stored_result_required_and_conflicting_host_receipt_refused(execution, store):
    runtime, task, run = execution
    with pytest.raises(DomainError, match="TASK_RESULT_REQUIRED"):
        await store.call(lambda db: record_execution_result(db, task["id"], run["id"]), write=True)
    result = {"state": "succeeded", "summary": "Actual result"}
    await runtime.tasks.report("alice", task["id"], run["id"], 1, result)
    await store.call(
        lambda db: db.execute(
            "UPDATE events SET payload_json='{}' WHERE task_id=? AND kind=?", (task["id"], KIND)
        ),
        write=True,
    )
    with pytest.raises(DomainError, match="TASK_RESULT_RECEIPT_CONFLICT"):
        await store.call(lambda db: receipt_for_run(db, task["id"], run["id"]))


async def test_changed_execution_result_cannot_be_attached_to_stale_completion(execution, store):
    runtime, task, run = execution
    old = {"state": "failed", "summary": "Initially unknown", "outcomeKnown": False}
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='running' WHERE id=?", (task["id"],)),
        write=True,
    )
    await runtime.dispatch.complete(task, run, old, "interrupted", unknown=True)
    old_run = await store.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE id=?", (run["id"],))
    )
    known = {"state": "succeeded", "summary": "Actually completed", "outcomeKnown": True}
    await runtime.tasks.report("alice", task["id"], run["id"], 1, known)
    # A stale verifier cannot associate its old bytes with the newer host identity.
    with pytest.raises(DomainError, match="TASK_RESULT_SUPERSEDED"):
        await store.call(
            lambda db: receipt_for_run(
                db, task["id"], run["id"], expected_result_json=old_run["result_json"]
            )
        )
    assert len(await facts(store, task)) == 2


async def test_late_old_revision_records_fact_without_changing_new_task(execution, store):
    runtime, task, run = execution
    await store.call(
        lambda db: db.execute(
            "UPDATE tasks SET revision=2,state='queued' WHERE id=?", (task["id"],)
        ),
        write=True,
    )
    await runtime.tasks.report(
        "alice", task["id"], run["id"], 1, {"state": "succeeded", "summary": "Late old result"}
    )
    current = await store.call(
        lambda db: row(db, "SELECT revision,state FROM tasks WHERE id=?", (task["id"],))
    )
    assert current == {"revision": 2, "state": "queued"}
    events = await facts(store, task)
    assert len(events) == 1 and json.loads(events[0]["payload_json"])["taskRevision"] == 1
    assert not await store.call(
        lambda db: row(
            db, "SELECT id FROM jobs WHERE kind='task.verify' AND aggregate_id=?", (task["id"],)
        )
    )


async def test_forgotten_result_identity_stays_out_of_model_task_status(execution, store):
    runtime, task, run = execution
    await runtime.tasks.report(
        "alice", task["id"], run["id"], 1, {"state": "succeeded", "summary": "Private source"}
    )
    await store.call(
        lambda db: db.execute(
            "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'forgotten',1)",
            (task["origin_message_id"],),
        ),
        write=True,
    )
    model_status = await runtime.tasks.list("alice", task_id=task["id"], for_model=True)
    assert len(model_status) == 1 and model_status[0]["contextExcluded"] is True
    assert "executionReceipt" not in encoded(model_status) and "Private source" not in encoded(
        model_status
    )
    assert len(await facts(store, task)) == 1


async def test_legacy_partial_result_remains_readable_without_a_receipt(execution, store):
    runtime, task, run = execution
    await store.call(
        lambda db: db.execute(
            "UPDATE task_attempts SET result_json=? WHERE id=?",
            (encoded({"summary": "Historical partial result"}), run["id"]),
        ),
        write=True,
    )
    view = await runtime.tasks.get("alice", task["id"])
    assert view["task"]["latestAttempt"]["summary"] == "Historical partial result"
    assert "executionReceipt" not in view["task"]["latestAttempt"]
    assert not await facts(store, task)
