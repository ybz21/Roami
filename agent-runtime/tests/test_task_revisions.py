"""Steering preserves attempts, waits for stop and fences stale callbacks."""

import asyncio
import json

import httpx
import pytest
from test_runtime import ConversationModel, until
from test_task_cancellation import task_run, verification

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.http import create_app
from roami_agent.storage.database import row, rows


async def finished(runtime, conversation, goal="Original goal"):
    task, run = await task_run(runtime, conversation, goal)
    result = {"state": "succeeded", "summary": "Original executor evidence"}
    await runtime.tasks.report("alice", task["id"], run["id"], 1, result)
    await runtime.dispatch.verify(await verification(runtime, task))
    return task, run, result


async def test_terminal_steering_preserves_attempts_deduplicates_and_fences_old_completion(store):
    runtime = Runtime(store, ConversationModel())
    try:
        conversation = await runtime.conversations.create("alice")
        task, old, evidence = await finished(runtime, conversation)
        operation = await runtime.tasks.revisions.request(
            "alice", task["id"], "Also check the second item", 1, "steer"
        )
        assert operation["state"] == "stopping"
        assert (
            await runtime.tasks.revisions.request(
                "alice", task["id"], "Also check the second item", 1, "steer"
            )
            == operation
        )
        with pytest.raises(DomainError, match="TASK_STEER_KEY_CONFLICT"):
            await runtime.tasks.revisions.request("alice", task["id"], "different", 1, "steer")
        await runtime.tasks.revisions.advance()
        applied = await runtime.tasks.revisions.get("alice", task["id"], operation["operationId"])
        assert applied["state"] == "applied" and applied["revision"] == 2
        replay = await runtime.tasks.create(
            "alice", conversation["id"], "Original goal", key="Original goal", record_intent=True
        )
        assert replay["id"] == task["id"] and replay["revision"] == 2
        assert (
            await runtime.tasks.revisions.request(
                "alice", task["id"], "Also check the second item", 1, "steer"
            )
            == applied
        )
        attempts = await store.call(
            lambda db: rows(
                db, "SELECT * FROM task_attempts WHERE task_id=? ORDER BY attempt_no", (task["id"],)
            )
        )
        assert len(attempts) == 2 and json.loads(attempts[0]["result_json"]) == evidence
        assert attempts[1]["native_branch_id"] == old["native_branch_id"]
        assert attempts[1]["task_revision"] == 2 and attempts[1]["state"] == "accepted"
        stale = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE dedupe_key=?",
                ("task.completion:" + old["id"] + ":succeeded",),
            )
        )
        assert await runtime.mailbox.claim(stale) is None
        with pytest.raises(DomainError, match="TASK_REVISION_CHANGED"):
            await runtime.tasks.revisions.request("alice", task["id"], "stale", 1, "stale")
        await runtime.start()
        await until(
            store,
            lambda db: row(
                db,
                "SELECT id FROM tasks WHERE id=? AND revision=2 AND state='succeeded'",
                (task["id"],),
            ),
        )
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE trigger_kind='completion' AND state='completed'"
            ),
        )
        messages = (await runtime.conversations.messages("alice", conversation["id"]))["messages"]
        assert sum(m["role"] == "assistant" for m in messages) == 1
        assert any(m["content"].get("taskSteer") == task["id"] for m in messages)
    finally:
        await runtime.close()


async def test_active_steering_stops_the_old_worker_before_starting_new_revision(store):
    class Worker:
        model = "steered-worker"

        def __init__(self):
            self.entered, self.stopped = asyncio.Event(), asyncio.Event()
            self.calls = 0

        async def stream(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                self.entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    self.stopped.set()
            assert self.stopped.is_set()
            yield ModelEvent("text", "Updated task completed")

    worker = Worker()
    runtime = Runtime(
        store, ConversationModel(), worker_model=worker, memory_model=ConversationModel()
    )
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", conversation["id"], "initial", key="active", record_intent=True
        )
        await runtime.start()
        await asyncio.wait_for(worker.entered.wait(), 2)
        operation = await runtime.tasks.revisions.request(
            "alice", task["id"], "updated requirement", 1, "update"
        )
        await until(
            store,
            lambda db: row(
                db,
                "SELECT id FROM tasks WHERE id=? AND revision=2 AND state='succeeded'",
                (task["id"],),
            ),
        )
        assert worker.stopped.is_set() and worker.calls == 2
        assert (await runtime.tasks.revisions.get("alice", task["id"], operation["operationId"]))[
            "state"
        ] == "applied"
        attempts = await store.call(
            lambda db: rows(
                db, "SELECT * FROM task_attempts WHERE task_id=? ORDER BY attempt_no", (task["id"],)
            )
        )
        assert attempts[0]["state"] == "cancelled" and attempts[1]["state"] == "succeeded"
        assert not await store.call(
            lambda db: row(
                db,
                "SELECT id FROM jobs WHERE dedupe_key=?",
                ("task.completion:" + attempts[0]["id"] + ":cancelled",),
            )
        )
    finally:
        await runtime.close()


async def test_steering_survives_restart_and_is_owner_scoped(store):
    runtime = Runtime(store, ConversationModel())
    conversation = await runtime.conversations.create("alice")
    task, _, _ = await finished(runtime, conversation)
    operation = await runtime.tasks.revisions.request(
        "alice", task["id"], "continued after restart", 1, "restart"
    )
    await runtime.close()
    restarted = Runtime(store, ConversationModel())
    try:
        transport = httpx.ASGITransport(app=create_app(restarted, manage_lifecycle=False))
        async with httpx.AsyncClient(transport=transport, base_url="http://runtime") as client:
            path = "/v1/tasks/" + task["id"] + "/steering/" + operation["operationId"]
            assert (await client.get(path, headers={"X-Roami-Owner": "bob"})).status_code == 404
            assert (
                await client.post(
                    "/v1/tasks/" + task["id"] + "/steer",
                    headers={"X-Roami-Owner": "bob"},
                    json={"requestKey": "other", "revision": 1, "text": "intrusion"},
                )
            ).status_code == 404
        await restarted.start()
        await until(
            store,
            lambda db: row(
                db,
                "SELECT id FROM tasks WHERE id=? AND revision=2 AND state='succeeded'",
                (task["id"],),
            ),
        )
    finally:
        await restarted.close()


async def test_unknown_outcome_blocks_steering_without_replaying_or_replacing_evidence(store):
    runtime = Runtime(store, ConversationModel())
    try:
        conversation = await runtime.conversations.create("alice")
        task, run = await task_run(runtime, conversation, "unknown")
        await runtime.dispatch.complete(
            task,
            run,
            {"state": "failed", "outcomeKnown": False, "retryable": False},
            "interrupted",
            unknown=True,
        )
        operation = await runtime.tasks.revisions.request(
            "alice", task["id"], "continue", 1, "continue"
        )
        await runtime.tasks.revisions.advance()
        receipt = await runtime.tasks.revisions.get("alice", task["id"], operation["operationId"])
        assert receipt["state"] == "blocked" and receipt["errorCode"] == "TASK_OUTCOME_UNRESOLVED"
        assert (
            await store.call(
                lambda db: db.execute(
                    "SELECT COUNT(*) FROM task_attempts WHERE task_id=?", (task["id"],)
                ).fetchone()[0]
            )
            == 1
        )
    finally:
        await runtime.close()


async def test_forgetting_old_task_source_invalidates_continued_revision(store):
    runtime = Runtime(store, ConversationModel())
    try:
        conversation = await runtime.conversations.create("alice")
        task, _, _ = await finished(runtime, conversation, "private original goal")
        saved = await runtime.memory.save(
            "alice", "private", "private original goal", task["origin_message_id"]
        )
        await runtime.tasks.revisions.request(
            "alice", task["id"], "continue with another check", 1, "continue"
        )
        await runtime.tasks.revisions.advance()
        current = (await runtime.tasks.list("alice"))[0]
        assert current["revision"] == 2
        await runtime.memory.forget("alice", saved["id"])
        assert (await runtime.tasks.list("alice", for_model=True))[0]["contextExcluded"]
    finally:
        await runtime.close()


async def test_new_root_revision_does_not_join_failed_children_from_an_old_revision(store):
    async def independent_verifier(task, result):
        return True

    runtime = Runtime(store, ConversationModel(), verifier=independent_verifier)
    try:
        conversation = await runtime.conversations.create("alice")
        root, original = await task_run(runtime, conversation, "root")
        child, child_run = await task_run(runtime, conversation, "old child", root["id"])
        await runtime.tasks.report("alice", child["id"], child_run["id"], 1, {"state": "failed"})
        await runtime.dispatch.verify(await verification(runtime, child))
        await runtime.tasks.report(
            "alice",
            root["id"],
            original["id"],
            1,
            {"state": "succeeded", "summary": "Original response"},
        )
        await runtime.dispatch.verify(await verification(runtime, root))
        await runtime.tasks.revisions.request(
            "alice", root["id"], "Finish with a different approach", 1, "retry-root"
        )
        await runtime.tasks.revisions.advance()
        current = await store.call(
            lambda db: row(
                db, "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=2", (root["id"],)
            )
        )
        assert current
        await runtime.tasks.report(
            "alice",
            root["id"],
            current["id"],
            2,
            {"state": "succeeded", "summary": "Updated response"},
        )
        job = await store.call(
            lambda db: row(
                db, "SELECT * FROM jobs WHERE dedupe_key=?", ("verify:" + current["id"],)
            )
        )
        await runtime.dispatch.verify(job)
        task = await store.call(lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (root["id"],)))
        assert task["state"] == "succeeded" and task["revision"] == 2
        await runtime.tasks.report(
            "alice",
            root["id"],
            original["id"],
            1,
            {"state": "succeeded", "summary": "Original response"},
        )
        task = await store.call(lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (root["id"],)))
        assert task["state"] == "succeeded" and task["revision"] == 2
    finally:
        await runtime.close()


async def test_success_claim_with_unknown_effect_is_never_accepted_by_verifier(store):
    async def verifier(task, result):
        pytest.fail("Unknown execution must reconcile before verification")

    runtime = Runtime(store, ConversationModel(), verifier=verifier)
    try:
        conversation = await runtime.conversations.create("alice")
        task, run = await task_run(runtime, conversation, "uncertain-success")
        await runtime.tasks.report(
            "alice",
            task["id"],
            run["id"],
            1,
            {"state": "succeeded", "summary": "Unproven success claim", "outcomeKnown": False},
        )
        await runtime.dispatch.verify(await verification(runtime, task))
        current = await store.call(
            lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],))
        )
        assert current["state"] == "interrupted"
    finally:
        await runtime.close()


async def test_explicit_cancel_revokes_a_queued_steering_request(store):
    runtime = Runtime(store, ConversationModel())
    try:
        conversation = await runtime.conversations.create("alice")
        task, _, _ = await finished(runtime, conversation)
        operation = await runtime.tasks.revisions.request(
            "alice", task["id"], "continue later", 1, "queued"
        )
        await runtime.tasks.cancel("alice", task["id"])
        await runtime.tasks.revisions.advance()
        receipt = await runtime.tasks.revisions.get("alice", task["id"], operation["operationId"])
        assert receipt["state"] == "cancelled" and receipt["revision"] == 1
        assert (
            await store.call(
                lambda db: db.execute(
                    "SELECT COUNT(*) FROM task_attempts WHERE task_id=?", (task["id"],)
                ).fetchone()[0]
            )
            == 1
        )
    finally:
        await runtime.close()


async def test_inflight_main_reply_cannot_publish_an_obsolete_task_result(store):
    entered, release = asyncio.Event(), asyncio.Event()

    class WaitingMain:
        model = "completion-race"

        async def stream(self, messages, tools):
            entered.set()
            await release.wait()
            yield ModelEvent("text", "Obsolete task completion")

    runtime = Runtime(store, WaitingMain())
    handle = None
    try:
        conversation = await runtime.conversations.create("alice")
        task, old, _ = await finished(runtime, conversation)
        job = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE dedupe_key=?",
                ("task.completion:" + old["id"] + ":succeeded",),
            )
        )
        turn = await runtime.mailbox.claim(job)
        handle = asyncio.create_task(
            runtime.loop.run(turn, "main", completion=json.loads(job["payload_json"])["completion"])
        )
        await asyncio.wait_for(entered.wait(), 2)
        await runtime.tasks.revisions.request(
            "alice", task["id"], "updated before reply", 1, "race"
        )
        await runtime.tasks.revisions.advance()
        release.set()
        with pytest.raises(DomainError, match="TASK_RESULT_SUPERSEDED"):
            await handle
        assert not await store.call(
            lambda db: row(
                db,
                "SELECT id FROM events WHERE turn_id=? AND kind='message.completed'",
                (turn["id"],),
            )
        )
        assert not await store.call(lambda db: row(db, "SELECT id FROM deliveries"))
    finally:
        release.set()
        if handle:
            await asyncio.gather(handle, return_exceptions=True)
        await runtime.close()


async def test_continuation_cannot_bypass_unaccepted_writes_but_accepted_history_can_continue_read_only(
    store, tmp_path
):
    import sys
    from contextlib import asynccontextmanager

    from roami_agent.server.configuration import Settings

    class Worker:
        model = "write-then-read"

        async def stream(self, messages, tools):
            if messages[-1]["role"] == "tool":
                yield ModelEvent("text", "Created the proof file")
            elif messages[-1]["content"].startswith("Continue the existing task"):
                yield ModelEvent("text", "Read-only follow-up answer")
            else:
                yield ModelEvent(
                    "tool",
                    {
                        "id": "write",
                        "type": "function",
                        "function": {
                            "name": "shell",
                            "arguments": json.dumps(
                                {
                                    "argv": [
                                        sys.executable,
                                        "-c",
                                        "from pathlib import Path; Path('proof.txt').write_text('verified')",
                                    ]
                                }
                            ),
                        },
                    },
                )

    @asynccontextmanager
    async def workspace(settings, task, run, **kwargs):
        yield {"directory": str(tmp_path), "workspaceId": "verification-fixture"}

    runtime = Runtime(
        store,
        ConversationModel(),
        worker_model=Worker(),
        memory_model=ConversationModel(),
        settings=Settings(timeout_seconds=5),
    )
    runtime.dispatch.native_executor.workspace_factory = workspace
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            conversation["id"],
            "Write proof",
            key="write-first",
            record_intent=True,
            target={"kind": "new_session", "directory": str(tmp_path)},
        )
        await runtime.start()

        async def reached(revision, state):
            await until(
                store,
                lambda db: row(
                    db,
                    "SELECT id FROM tasks WHERE id=? AND revision=? AND state=?",
                    (task["id"], revision, state),
                ),
            )

        await reached(1, "waiting_user")
        assert (tmp_path / "proof.txt").read_text() == "verified"
        await runtime.tasks.revisions.request(
            "alice", task["id"], "Answer a follow-up without writing", 1, "read-only-unaccepted"
        )
        await reached(2, "waiting_user")
        assert (tmp_path / "proof.txt").read_text() == "verified"
        await runtime.dispatch.confirm("alice", task["id"], True)
        await runtime.tasks.revisions.request(
            "alice", task["id"], "Another read-only follow-up", 2, "read-only-accepted"
        )
        await reached(3, "succeeded")
        attempts = await store.call(
            lambda db: rows(
                db,
                "SELECT result_json FROM task_attempts WHERE task_id=? ORDER BY task_revision",
                (task["id"],),
            )
        )
        assert all(
            json.loads(attempt["result_json"])["state"] == "succeeded" for attempt in attempts
        )
    finally:
        await runtime.close()


async def test_waiting_for_acceptance_is_not_discarded_when_verifier_becomes_unavailable(store):
    async def not_verified(task, result):
        return False

    runtime = Runtime(store, ConversationModel(), verifier=not_verified)
    try:
        conversation = await runtime.conversations.create("alice")
        task, _, _ = await finished(runtime, conversation)
        runtime.dispatch.verifier = None
        await runtime.tasks.revisions.request("alice", task["id"], "Continue reading", 1, "reading")
        await runtime.tasks.revisions.advance()
        run = await store.call(
            lambda db: row(
                db, "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=2", (task["id"],)
            )
        )
        await runtime.tasks.report(
            "alice",
            task["id"],
            run["id"],
            2,
            {"state": "succeeded", "summary": "A read-only response"},
        )
        job = await store.call(
            lambda db: row(db, "SELECT * FROM jobs WHERE dedupe_key=?", ("verify:" + run["id"],))
        )
        await runtime.dispatch.verify(job)
        current = await store.call(
            lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],))
        )
        assert current["state"] == "waiting_user"
    finally:
        await runtime.close()


@pytest.mark.parametrize("state", ["succeeded", "failed", "waiting_user"])
async def test_completion_cannot_invent_user_steering_but_a_new_user_request_can(store, state):
    from test_runtime import ConversationModel

    from roami_agent.app import Runtime

    runtime = Runtime(store, ConversationModel())
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", conversation["id"], "Create report", key="handoff", record_intent=True
        )
        run = await store.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
        )
        await runtime.dispatch.complete(
            task, run, {"state": "succeeded", "summary": "Existing evidence"}, state
        )
        job = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE kind='turn.run' AND json_extract(payload_json,'$.completion.taskId')=?",
                (task["id"],),
            )
        )
        turn = await runtime.mailbox.claim(job)
        before = await store.call(
            lambda db: db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        )
        with pytest.raises(DomainError, match="TASK_STEER_USER_REQUEST_REQUIRED"):
            await runtime.tasks.revisions.request(
                "alice",
                task["id"],
                "Try again without new user input",
                1,
                "callback",
                source_turn_id=turn["id"],
                source_conversation_id=conversation["id"],
            )
        assert (
            await store.call(lambda db: db.execute("SELECT COUNT(*) FROM messages").fetchone()[0])
            == before
        )
        assert not await store.call(
            lambda db: row(db, "SELECT id FROM jobs WHERE kind='task.steer'")
        )
        await runtime.loop.run(
            turn, "main", completion=json.loads(job["payload_json"])["completion"]
        )
        receipt = await runtime.conversations.accept(
            "alice", conversation["id"], "continue", "Continue the original task and fix the error."
        )
        user_job = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?",
                (receipt["turnId"],),
            )
        )
        user_turn = await runtime.mailbox.claim(user_job)
        continuation = await runtime.tasks.revisions.request(
            "alice",
            task["id"],
            "Fix the error",
            1,
            "user",
            source_turn_id=user_turn["id"],
            source_conversation_id=conversation["id"],
        )
        assert continuation["taskId"] == task["id"]
        assert continuation["state"] == "stopping"
    finally:
        await runtime.close()
