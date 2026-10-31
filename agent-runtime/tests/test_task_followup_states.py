"""All task executors share revision fencing across completed and unfinished work."""

import json

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row, rows

EXECUTORS = ("native", "codex", "claude", "opencode", "pi")
STATES = (
    "queued",
    "preparing",
    "running",
    "verifying",
    "cancelling",
    "succeeded",
    "waiting_user",
    "failed",
    "cancelled",
    "interrupted",
)
ACTIVE = {"queued", "preparing", "running", "verifying", "cancelling"}


async def create_task(runtime, executor):
    conversation = await runtime.conversations.create("alice")
    task = await runtime.tasks.create(
        "alice",
        conversation["id"],
        "Original requirement",
        key="original",
        executor=executor,
        target={"kind": "new_session"}
        if executor == "native"
        else {
            "kind": "session",
            "sessionId": "original-session",
        },
        record_intent=True,
    )
    run = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    return task, run


@pytest.mark.parametrize("executor", EXECUTORS)
@pytest.mark.parametrize("prior_state", STATES)
async def test_followup_retains_executor_context_and_waits_for_old_work_to_stop(
    store,
    executor,
    prior_state,
):
    settings = Settings(workers=1)
    coding = CodingExecutor(store, settings)
    runtime = Runtime(store, ConversationModel(), settings=settings, executor=coding)
    launches = []

    async def command(sub, *args, spec=None):
        if sub == "launch":
            launches.append(spec)
            return {"state": "running", "session": "original-session"}
        assert sub == "status"
        return {
            "state": "succeeded",
            "session": "original-session",
            "result": {"state": "succeeded", "summary": "Updated result"},
        }

    coding.command = command
    try:
        task, old = await create_task(runtime, executor)
        result = {
            "state": "failed"
            if prior_state in {"failed", "interrupted"}
            else "cancelled"
            if prior_state == "cancelled"
            else "succeeded",
            "summary": "Original evidence",
            "inputStopped": True,
            "outcomeKnown": True,
        }
        has_result = prior_state not in ACTIVE or prior_state == "verifying"

        def seed(db):
            db.execute("UPDATE tasks SET state=? WHERE id=?", (prior_state, task["id"]))
            db.execute(
                "UPDATE task_attempts SET state=?,session_id=?,result_json=? WHERE id=?",
                (
                    result["state"]
                    if has_result
                    else "accepted"
                    if prior_state == "queued"
                    else "starting"
                    if prior_state == "preparing"
                    else "running",
                    None if executor == "native" else "original-session",
                    json.dumps(result) if has_result else None,
                    old["id"],
                ),
            )
            db.execute("UPDATE jobs SET state='done' WHERE aggregate_id=?", (task["id"],))

        await store.call(seed, write=True)
        operation = await runtime.tasks.revisions.request(
            "alice",
            task["id"],
            "Append this requirement",
            1,
            "followup",
        )
        assert (
            await runtime.tasks.revisions.request(
                "alice",
                task["id"],
                "Append this requirement",
                1,
                "followup",
            )
            == operation
        )
        await runtime.tasks.revisions.advance()
        if prior_state in ACTIVE:
            current = (await runtime.tasks.list("alice"))[0]
            assert current["revision"] == 1 and current["state"] == "cancelling"
            assert not launches
            assert (
                await store.call(
                    lambda db: db.execute("SELECT COUNT(*) FROM task_attempts").fetchone()[0]
                )
                == 1
            )
            if not has_result:
                result = {
                    "state": "cancelled",
                    "summary": "Old execution stopped",
                    "inputStopped": True,
                    "outcomeKnown": True,
                }
                await runtime.tasks.report("alice", task["id"], old["id"], 1, result)
            verification = await store.call(
                lambda db: row(
                    db, "SELECT * FROM jobs WHERE kind='task.verify' ORDER BY rowid DESC LIMIT 1"
                )
            )
            await runtime.dispatch.verify(verification)
            await runtime.tasks.revisions.advance()
        receipt = await runtime.tasks.revisions.get("alice", task["id"], operation["operationId"])
        assert receipt["state"] == "applied" and receipt["revision"] == 2
        attempts = await store.call(
            lambda db: rows(db, "SELECT * FROM task_attempts ORDER BY attempt_no")
        )
        assert len(attempts) == 2
        new = attempts[1]
        assert new["executor_kind"] == ("native" if executor == "native" else "cli")
        assert new["native_branch_id"] == old["native_branch_id"]
        assert json.loads(attempts[0]["result_json"]) == result
        # Old callbacks cannot complete or replace the appended revision.
        await runtime.tasks.report("alice", task["id"], old["id"], 1, result)
        job = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE kind='task.run' AND json_extract(payload_json,'$.runId')=?",
                (new["id"],),
            )
        )
        await runtime.scheduler._job(job)
        if executor != "native":
            assert len(launches) == 1
            assert launches[0]["executor"] == executor
            assert launches[0]["sessionId"] == "original-session"
            assert launches[0]["prompt"] == "Append this requirement"
            await coding.poll(runtime.tasks)
        verification = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE kind='task.verify' ORDER BY rowid DESC LIMIT 1",
            )
        )
        await runtime.dispatch.verify(verification)
        current = (await runtime.tasks.list("alice"))[0]
        expected = (
            "succeeded"
            if executor == "native" and prior_state != "waiting_user"
            else "waiting_user"
        )
        assert current["state"] == expected and current["revision"] == 2
        if executor == "native":
            assert "Append this requirement" in current["latestAttempt"]["summary"]
        events = await runtime.conversations.events("alice", task["origin_conversation_id"])
        assert not any(e["kind"] == "task.failed" for e in events)
    finally:
        await runtime.close()


@pytest.mark.parametrize("executor", EXECUTORS)
@pytest.mark.parametrize("closure", ["closing", "closed"])
async def test_followup_respects_explicit_session_closure(store, executor, closure):
    runtime = Runtime(store, ConversationModel())
    try:
        task, old = await create_task(runtime, executor)
        await store.call(
            lambda db: db.execute(
                "INSERT INTO task_session_closures(task_id,task_revision,run_id,launch_id,"
                "session_id,state,updated_ms) VALUES(?,1,?,?,?, ?,0)",
                (task["id"], old["id"], old["launch_id"], "original-session", closure),
            ),
            write=True,
        )
        code = "TASK_SESSION_CLOSED" if closure == "closed" else "TASK_SESSION_CLOSING"
        with pytest.raises(DomainError, match=code):
            await runtime.tasks.revisions.request("alice", task["id"], "Continue", 1, "followup")
        assert not await store.call(
            lambda db: row(db, "SELECT id FROM jobs WHERE kind='task.steer'")
        )
        assert (await runtime.tasks.list("alice"))[0]["revision"] == 1
    finally:
        await runtime.close()


@pytest.mark.parametrize("executor", EXECUTORS)
@pytest.mark.parametrize("uncertainty", ["outcomeKnown", "inputStopped"])
async def test_followup_does_not_replace_unresolved_execution(store, executor, uncertainty):
    runtime = Runtime(store, ConversationModel())
    try:
        task, old = await create_task(runtime, executor)
        await store.call(
            lambda db: db.execute(
                "UPDATE tasks SET state='running' WHERE id=?",
                (task["id"],),
            ),
            write=True,
        )
        result = {"state": "failed", "summary": "Stop unconfirmed", uncertainty: False}
        await runtime.dispatch.complete(task, old, result, "interrupted", unknown=True)
        with pytest.raises(DomainError, match="TASK_OUTCOME_UNRESOLVED"):
            await runtime.tasks.revisions.request("alice", task["id"], "Continue", 1, "followup")
        assert not await store.call(
            lambda db: row(db, "SELECT id FROM jobs WHERE kind='task.steer'")
        )
        assert (
            await store.call(
                lambda db: db.execute("SELECT COUNT(*) FROM task_attempts").fetchone()[0]
            )
            == 1
        )
    finally:
        await runtime.close()
