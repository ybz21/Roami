"""Native timing is current runtime data, never a new execution budget."""

import json
from copy import deepcopy

import pytest
from test_compaction_threshold import SummaryModel

from roami_agent.context.projection import Context
from roami_agent.context.prompt_builder import PromptBuilder
from roami_agent.conversation.transcript import Conversations
from roami_agent.executors.native import NativeExecutor
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


@pytest.mark.parametrize("deadline", [0, 25001])
async def test_clock_refreshes_at_prompt_tail_without_changing_prefix_or_history(
    store, monkeypatch, deadline
):
    conversations = Conversations(store)
    c = await conversations.create("alice")
    receipt = await conversations.accept("alice", c["id"], "clock", "Finish the original task")
    turn = await store.call(
        lambda db: dict(
            row(db, "SELECT * FROM turns WHERE id=?", (receipt["turnId"],)), owner_id="alice"
        )
    )
    turn.update(
        executionRunId="attempt-two", executionStartedMs=10000, executionDeadlineMs=deadline
    )
    original = deepcopy(turn)
    clock = iter([17000, 19000])
    monkeypatch.setattr(
        "roami_agent.context.prompt_builder.now_ms", lambda: next(clock), raising=False
    )
    builder = PromptBuilder(store, Context(store, SummaryModel()), Settings())
    first, prompt = await builder.build(turn, "Original worker instructions", [], None)
    second, updated = await builder.build(turn, "Original worker instructions", [], None)
    assert first["executionTiming"]["elapsedSeconds"] == 7
    assert second["executionTiming"]["elapsedSeconds"] == 9
    assert second["executionTiming"]["runId"] == "attempt-two"
    assert prompt[:-1] == updated[:-1]
    assert prompt[-1]["role"] == updated[-1]["role"] == "system"
    assert prompt[-2]["content"] == "Finish the original task"
    assert (
        json.dumps(
            first["executionTiming"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        in prompt[-1]["content"]
    )
    assert prompt[-1] != updated[-1]
    assert first["requestBasis"] == second["requestBasis"]
    assert turn == original
    assert len((await conversations.messages("alice", c["id"]))["messages"]) == 1
    if deadline:
        assert first["executionTiming"]["remainingSeconds"] == 9
        assert second["executionTiming"]["remainingSeconds"] == 7
    else:
        assert "remainingSeconds" not in first["executionTiming"]
        assert "deadlineMs" not in first["executionTiming"]


@pytest.mark.parametrize("started", [None, 0, True, "1000", -1])
async def test_missing_attempt_start_does_not_invent_a_clock(store, started):
    conversations = Conversations(store)
    c = await conversations.create("alice")
    receipt = await conversations.accept("alice", c["id"], "missing", "Continue")
    turn = await store.call(
        lambda db: dict(
            row(db, "SELECT * FROM turns WHERE id=?", (receipt["turnId"],)), owner_id="alice"
        )
    )
    builder = PromptBuilder(store, Context(store, SummaryModel()), Settings())
    plain, prompt = await builder.build(turn, "", [], None)
    turn.update(executionStartedMs=started, executionRunId="attempt")
    plan, worker_prompt = await builder.build(turn, "", [], None)
    assert "executionTiming" not in plain and "executionTiming" not in plan
    assert prompt[-1]["content"] == worker_prompt[-1]["content"] == "Continue"


@pytest.mark.parametrize("known_start", [None, 12000])
async def test_native_executor_passes_attempt_start_and_only_existing_deadline(
    monkeypatch, known_start
):
    monkeypatch.setattr("roami_agent.executors.native.now_ms", lambda: 15000)
    observed = []

    async def worker(turn, role, *, task_id):
        observed.append(turn)
        raise RuntimeError("captured before completion")

    task = {
        "id": "task",
        "owner_id": "alice",
        "intent_json": json.dumps({"target": {"kind": "new_session"}}),
        "budget_json": json.dumps({"deadlineMs": 0}),
    }
    run = {"id": "current-attempt", "native_branch_id": "branch", "started_ms": known_start}
    with pytest.raises(RuntimeError, match="captured"):
        await NativeExecutor(worker).run(task, run, turn={"branch_id": "branch", "created_ms": 1})
    assert observed[0]["executionStartedMs"] == (known_start or 15000)
    assert observed[0].get("executionDeadlineMs") in [None, 0]
    assert observed[0]["executionTimeoutSeconds"] is None
    assert json.loads(task["budget_json"]) == {"deadlineMs": 0}


@pytest.mark.parametrize("observed,elapsed,remaining", [(9000, 0, 17), (26001, 16, 0)])
def test_clock_handles_future_start_and_expired_existing_deadline(observed, elapsed, remaining):
    from roami_agent.context.execution_timing import execution_timing

    turn = {"executionRunId": "attempt", "executionStartedMs": 10000, "executionDeadlineMs": 25001}
    value = execution_timing(turn, observed)
    assert value["elapsedSeconds"] == elapsed
    assert value["remainingSeconds"] == remaining


async def test_dispatcher_passes_persisted_attempt_start_instead_of_queue_timestamp(store):
    from test_runtime import ConversationModel

    from roami_agent.app import Runtime

    runtime = Runtime(store, ConversationModel())
    captured = []

    async def worker(turn, role, *, task_id):
        captured.append(turn)
        return "Completed"

    runtime.dispatch.native_executor.run_turn = worker
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", conversation["id"], "Finish", key="clock-dispatch", record_intent=True
        )
        await store.call(
            lambda db: db.execute("UPDATE tasks SET created_ms=1 WHERE id=?", (task["id"],)),
            write=True,
        )
        job = await store.call(
            lambda db: row(
                db, "SELECT * FROM jobs WHERE kind='task.run' AND aggregate_id=?", (task["id"],)
            )
        )
        await runtime.dispatch.run(job)
        attempt = await store.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
        )
        assert captured[0]["executionStartedMs"] == attempt["started_ms"] > 1
        assert captured[0]["executionRunId"] == attempt["id"]
    finally:
        await runtime.close()


async def test_real_native_tool_loop_receives_one_fresh_clock_and_keeps_it_out_of_transcript(store):
    from test_runtime import ConversationModel

    from roami_agent.app import Runtime
    from roami_agent.protocol.models import ModelEvent
    from roami_agent.storage.database import rows

    observed = []

    class Worker:
        model = "clock-tool-loop"

        async def stream(self, messages, tools):
            clocks = [
                m
                for m in messages
                if isinstance(m.get("content"), str)
                and m["content"].startswith("Current native attempt timing")
            ]
            assert len(clocks) == 1 and messages[-1] == clocks[0]
            observed.append(deepcopy(messages))
            if len(observed) == 1:
                yield ModelEvent(
                    "tool",
                    {
                        "id": "read-skill",
                        "function": {
                            "name": "read",
                            "arguments": json.dumps({"path": "skill://browser_use"}),
                        },
                    },
                )
            else:
                assert any(m["role"] == "tool" for m in messages)
                yield ModelEvent("text", "Original task completed")

    runtime = Runtime(store, ConversationModel(), worker_model=Worker())
    try:
        c = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", c["id"], "Read the workflow", key="tool-clock", record_intent=True
        )
        job = await store.call(
            lambda db: row(
                db, "SELECT * FROM jobs WHERE kind='task.run' AND aggregate_id=?", (task["id"],)
            )
        )
        await runtime.dispatch.run(job)
        assert len(observed) == 2
        assert observed[1][: len(observed[0]) - 1] == observed[0][:-1]
        parts = await store.call(
            lambda db: rows(db, "SELECT parts_json FROM prompt_manifests ORDER BY created_ms")
        )
        assert len(parts) == 2
        for part, prompt in zip(parts, observed, strict=True):
            timing = json.loads(part["parts_json"])["executionTiming"]
            assert isinstance(timing, dict) and timing["runId"]
            assert (
                json.dumps(timing, separators=(",", ":"), sort_keys=True) in prompt[-1]["content"]
            )
        messages = await store.call(lambda db: rows(db, "SELECT content_json FROM messages"))
        assert all("Current native attempt timing" not in m["content_json"] for m in messages)
    finally:
        await runtime.close()
