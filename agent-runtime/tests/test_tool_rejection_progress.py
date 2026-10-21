"""Rejected calls can recover, but identical pre-execution failures cannot spin."""

import json

import pytest
from test_argument_repair_progress import claimed_turn

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.protocol.tools import Tool, object_schema


def bash(argv):
    return {"name": "bash", "arguments": json.dumps({"argv": argv})}


def observe(resource="owned"):
    return bash(
        [
            "roami",
            "agent",
            "capability",
            "call",
            "browser_observe",
            "--input",
            json.dumps({"resourceId": resource}),
        ]
    )


class Calls:
    model = "rejected-call-regression"

    def __init__(self, calls):
        self.script, self.calls, self.results = calls, 0, []

    async def stream(self, messages, tools):
        if messages[-1]["role"] == "tool":
            self.results.append(json.loads(messages[-1]["content"]))
        self.calls += 1
        if self.calls <= len(self.script):
            yield ModelEvent(
                "tool", {"id": str(self.calls), "function": self.script[self.calls - 1]}
            )
        else:
            yield ModelEvent("text", "Done")


@pytest.mark.parametrize(
    "role,call,disabled",
    [
        ("research", bash(["echo", "hello"]), False),
        ("main", bash(["echo", "hello"]), True),
        ("research", bash(["roami", "agent", "capability", "call", "browser_observe"]), False),
        ("main", {"name": "missing", "arguments": "{}"}, False),
    ],
)
async def test_identical_rejected_calls_stop_before_a_third_model_request(
    store, role, call, disabled
):
    model = Calls([call] * 30)
    runtime = Runtime(store, model, worker_model=model)
    if disabled:
        runtime.tools.disabled_tools.add("bash")
    try:
        with pytest.raises(DomainError, match="TOOL_ARGUMENT_REPAIR_STALLED"):
            await runtime.loop.run(await claimed_turn(runtime), role)
        assert model.calls == 2
    finally:
        await runtime.close()


def add_observer(runtime, effects):
    async def read(args, binding):
        effects.append(args["resourceId"])
        return {"observed": True}

    runtime.tools.add(
        Tool(
            "browser_observe",
            "Observe an owned browser resource",
            object_schema({"resourceId": {"type": "string"}}, ["resourceId"]),
            read,
        )
    )


async def test_research_can_change_rejected_arguments_and_recover_to_a_registered_call(store):
    model = Calls([bash(["echo", "hello"]), bash(["echo", "different"]), observe()])
    runtime, effects = Runtime(store, model, worker_model=model), []
    add_observer(runtime, effects)
    try:
        assert await runtime.loop.run(await claimed_turn(runtime), "research") == "Done"
        assert model.calls == 4 and effects == ["owned"]
        assert "roami chrome" in model.results[0]["recovery"]
    finally:
        await runtime.close()


async def test_research_catalog_does_not_advertise_a_standalone_shell(store):
    runtime = Runtime(store, Calls([]))
    try:
        tool = next(
            t["function"]
            for t in runtime.tools.catalog("research")
            if t["function"]["name"] == "bash"
        )
        assert "command" not in tool["parameters"]["properties"]
        assert tool["parameters"]["required"] == ["argv"]
        assert "only" in tool["description"] and "browser" in tool["description"]
        worker = next(
            t["function"]
            for t in runtime.tools.catalog("worker")
            if t["function"]["name"] == "bash"
        )
        assert "command" in worker["parameters"]["properties"]
    finally:
        await runtime.close()


async def test_valid_research_calls_have_no_old_round_limit(store):
    model = Calls([observe() for _ in range(25)])
    runtime, effects = Runtime(store, model, worker_model=model), []
    add_observer(runtime, effects)
    try:
        assert await runtime.loop.run(await claimed_turn(runtime), "research") == "Done"
        assert model.calls == 26 and len(effects) == 25
    finally:
        await runtime.close()


async def test_error_after_validated_read_execution_is_not_a_preexecution_rejection(store):
    model = Calls([observe(), observe()])
    runtime, reads = Runtime(store, model, worker_model=model), []

    async def unavailable(args, binding):
        reads.append(args["resourceId"])
        raise DomainError("TOOL_UNAVAILABLE")

    runtime.tools.add(
        Tool(
            "browser_observe",
            "Read an owned resource",
            object_schema({"resourceId": {"type": "string"}}, ["resourceId"]),
            unavailable,
        )
    )
    try:
        assert await runtime.loop.run(await claimed_turn(runtime), "research") == "Done"
        assert model.calls == 3 and reads == ["owned", "owned"]
        assert all("recovery" not in result for result in model.results)
    finally:
        await runtime.close()
