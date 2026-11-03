"""Ending a turn cannot silently drop actions from a tool batch."""

import json
from pathlib import Path

import pytest
from test_argument_repair_progress import claimed_turn
from test_coordinator_handoff import call

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.storage.database import rows

CONTROLS = json.loads(
    (
        Path(__file__).resolve().parents[2] / "cases/case-108-mech-tb02/input/controls.json"
    ).read_text()
)


def terminal_call(kind, key=None):
    arguments = CONTROLS["terminal_arguments"]
    return call(kind, arguments[kind], key)


def write_probe(runtime, effects):
    async def write(args, binding):
        effects.append(args["value"])
        return {"written": True}

    runtime.tools.add(
        Tool(
            "record_value",
            "Record a fixture value",
            object_schema({"value": {"type": "integer"}}, ["value"]),
            write,
            effect="write",
            main=True,
        )
    )


@pytest.mark.parametrize("kind", CONTROLS["ending_tools"])
@pytest.mark.parametrize("ending_first", CONTROLS["ending_first"])
async def test_mixed_ending_batch_is_repaired_before_any_action(store, kind, ending_first):
    effects = []

    class Main:
        model = "terminal-batch-fixture"
        calls = 0

        async def stream(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                batch = [call("record_value", {"value": 1}), terminal_call(kind)]
                for item in reversed(batch) if ending_first else batch:
                    yield ModelEvent("tool", item)
            else:
                assert self.calls == 2
                results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
                assert len(results) == 2
                assert all(
                    v["error"] == "QUESTION_MUST_BE_ONLY_TOOL" and v["executionStarted"] is False
                    for v in results
                )
                yield ModelEvent("text", "The invalid batch was corrected.")

    model = Main()
    runtime = Runtime(store, model)
    write_probe(runtime, effects)
    try:
        assert (
            await runtime.loop.run(await claimed_turn(runtime), "main")
            == "The invalid batch was corrected."
        )
        assert model.calls == 2 and not effects
        records = await store.call(lambda db: rows(db, "SELECT state FROM tool_calls"))
        assert len(records) == 2 and all(v["state"] == "failed" for v in records)
    finally:
        await runtime.close()


class BatchModel:
    model = "terminal-progress-fixture"

    def __init__(self, batches):
        self.batches, self.calls = batches, 0

    async def stream(self, messages, tools):
        batch = self.batches[self.calls]
        self.calls += 1
        if isinstance(batch, str):
            yield ModelEvent("text", batch)
        else:
            for item in batch:
                yield ModelEvent("tool", item)


async def test_valid_large_action_batches_keep_running_without_a_new_limit(store):
    effects = []
    model = BatchModel(
        [
            [
                call("record_value", {"value": i}, f"write-{i}")
                for i in range(CONTROLS["valid_action_count"])
            ],
            [terminal_call("reply", "final")],
        ]
    )
    runtime = Runtime(store, model)
    write_probe(runtime, effects)
    try:
        assert (
            await runtime.loop.run(await claimed_turn(runtime), "main")
            == "The requested answer is ready."
        )
        assert model.calls == 2 and effects == list(range(CONTROLS["valid_action_count"]))
    finally:
        await runtime.close()


async def test_valid_read_batches_do_not_require_separate_calls(store):
    effects = []

    async def read(args, binding):
        effects.append(args["value"])
        return {"value": args["value"]}

    model = BatchModel(
        [
            [call("read_value", {"value": i}, f"read-{i}") for i in range(3)],
            "The requested reads completed.",
        ]
    )
    runtime = Runtime(store, model)
    runtime.tools.add(
        Tool(
            "read_value",
            "Read a fixture value",
            object_schema({"value": {"type": "integer"}}, ["value"]),
            read,
            main=True,
        )
    )
    try:
        assert (
            await runtime.loop.run(await claimed_turn(runtime), "main")
            == "The requested reads completed."
        )
        assert model.calls == 2 and effects == [0, 1, 2]
    finally:
        await runtime.close()


async def test_successful_progress_allows_a_later_batch_repair(store):
    effects = []
    model = BatchModel(
        [
            [
                call("record_value", {"value": 1}, "bad-write-1"),
                terminal_call("reply", "bad-reply-1"),
            ],
            [call("record_value", {"value": 2}, "valid-write")],
            [
                call("record_value", {"value": 3}, "bad-write-2"),
                terminal_call("reply", "bad-reply-2"),
            ],
            "The corrected operations completed.",
        ]
    )
    runtime = Runtime(store, model)
    write_probe(runtime, effects)
    try:
        assert (
            await runtime.loop.run(await claimed_turn(runtime), "main")
            == "The corrected operations completed."
        )
        assert model.calls == 4 and effects == [2]
    finally:
        await runtime.close()


async def test_corrected_question_is_delivered_without_running_the_rejected_write(store):
    effects = []
    model = BatchModel(
        [
            [call("record_value", {"value": 1}), terminal_call("ask_user", "bad-question")],
            [terminal_call("ask_user", "fixed-question")],
        ]
    )
    runtime = Runtime(store, model)
    write_probe(runtime, effects)
    try:
        turn = await claimed_turn(runtime)
        assert await runtime.loop.run(turn, "main") == ""
        assert model.calls == 2 and not effects
        messages = await runtime.conversations.messages("alice", turn["conversation_id"])
        questions = [
            m["content"]["question"] for m in messages["messages"] if "question" in m["content"]
        ]
        assert len(questions) == 1 and questions[0]["prompt"] == "Choose the required destination."
    finally:
        await runtime.close()


async def test_single_terminal_tool_still_ends_the_turn_without_an_extra_model_call(store):
    model = BatchModel([[terminal_call("reply")]])
    runtime = Runtime(store, model)
    try:
        assert (
            await runtime.loop.run(await claimed_turn(runtime), "main")
            == "The requested answer is ready."
        )
        assert model.calls == 1
    finally:
        await runtime.close()


async def test_repeated_invalid_batches_stop_without_executing_writes(store):
    effects = []

    class Main:
        model = "repeated-terminal-batch-fixture"
        calls = 0

        async def stream(self, messages, tools):
            self.calls += 1
            assert self.calls <= 2, "Repeated invalid batches must stop without a request quota"
            yield ModelEvent(
                "tool", call("record_value", {"value": self.calls}, f"write-{self.calls}")
            )
            yield ModelEvent("tool", terminal_call("reply", f"reply-{self.calls}"))

    model = Main()
    runtime = Runtime(store, model)
    write_probe(runtime, effects)
    try:
        with pytest.raises(DomainError, match="TOOL_ARGUMENT_REPAIR_STALLED"):
            await runtime.loop.run(await claimed_turn(runtime), "main")
        assert model.calls == 2 and not effects
    finally:
        await runtime.close()
