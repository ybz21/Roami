"""Continuation rejections preserve work and explain the next safe decision."""

import json

import pytest
from test_assignment_recovery import active_turn, call
from test_routing_policy import setup

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row


@pytest.mark.parametrize("fault", ["revision", "pending", "session", "outcome"])
async def test_continuation_rejection_has_recovery_without_new_work(store, fault):
    runtime, targets, _, tools, binding = await setup(store, user="Continue the original work")
    runtime.gateway.tools = tools
    try:
        task = await runtime.tasks.create(
            "alice",
            binding["conversation"],
            "Original work",
            key="task",
            executor="codex",
            record_intent=True,
        )

        def seed(db):
            result = {
                "state": "failed" if fault == "outcome" else "succeeded",
                "inputStopped": True,
                "outcomeKnown": fault != "outcome",
            }
            db.execute(
                "UPDATE tasks SET state=? WHERE id=?",
                ("interrupted" if fault == "outcome" else "succeeded", task["id"]),
            )
            db.execute(
                "UPDATE task_attempts SET state=?,result_json=? WHERE task_id=?",
                ("unknown" if fault == "outcome" else "succeeded", json.dumps(result), task["id"]),
            )

        await store.call(seed, write=True)
        if fault == "pending":
            await runtime.tasks.revisions.request(
                "alice", task["id"], "Earlier continuation", 1, "earlier"
            )
        operation, args = (
            "task_steer",
            {
                "taskId": task["id"],
                "revision": 99 if fault == "revision" else 1,
                "text": "Continue the original work",
                "requestComplete": True,
            },
        )
        if fault == "session":

            async def missing(kind, ident):
                raise DomainError("SESSION_TARGET_NOT_FOUND")

            targets.resolve = missing
            operation, args = "target_resolve", {"kind": "session", "id": "expired-session"}
        result = await runtime.gateway.invoke(
            await active_turn(store, binding),
            binding["assistantMessageId"],
            call("continue", operation, args),
            "main",
            binding,
        )
        expected = {
            "revision": "TASK_REVISION_CHANGED",
            "pending": "TASK_STEER_PENDING",
            "session": "SESSION_TARGET_NOT_FOUND",
            "outcome": "TASK_OUTCOME_UNRESOLVED",
        }[fault]
        assert result["error"] == expected and result["executionStarted"] is False
        assert result["recovery"] and not targets.sends
        current = (await runtime.tasks.get("alice", task["id"]))["task"]
        assert current["revision"] == 1
        assert (
            await store.call(
                lambda db: db.execute("SELECT count(*) FROM task_attempts").fetchone()[0]
            )
            == 1
        )
        if fault == "outcome":
            assert current["latestAttempt"]["stopConfirmed"] is True
            assert current["latestAttempt"]["outcomeKnown"] is False
            assert "waiting alone" in result["recovery"] and result["retryable"] is False
        persisted = await store.call(
            lambda db: row(
                db,
                "SELECT m.content_json FROM messages m JOIN tool_calls x ON x.result_message_id=m.id WHERE x.turn_id=? ORDER BY x.created_ms DESC LIMIT 1",
                (binding["turnId"],),
            )
        )
        assert (
            json.loads(json.loads(persisted["content_json"])["text"])["recovery"]
            == result["recovery"]
        )
    finally:
        await runtime.close()
