"""An unchanged research blocker permits evidence delivery, never more inputs."""

import json

import pytest
from test_argument_repair_progress import claimed_turn
from test_coordinator_handoff import call
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError, ToolFinalizationRequired
from roami_agent.protocol.models import ModelEvent
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.storage.database import rows


@pytest.mark.parametrize("retries", [False, True])
async def test_finalization_delivers_existing_findings_without_another_tool_action(store, retries):
    effects, rounds = [], 0

    class Worker:
        model = "close-from-evidence"

        async def stream(self, messages, tools):
            nonlocal rounds
            rounds += 1
            if rounds == 1:
                yield ModelEvent("tool", call("blocked_source", {}))
                yield ModelEvent("tool", call("unexpected_write", {}))
            else:
                assert rounds == 2 and tools == []
                assert any(
                    "This attempt is closing" in m["content"]
                    for m in messages
                    if m["role"] == "system"
                )
                assert messages[-1]["role"] == "tool"
                assert json.loads(messages[-1]["content"])["error"] == "TOOL_FINALIZING_READ_ONLY"
                if retries:
                    yield ModelEvent("tool", call("unexpected_write", {}))
                else:
                    yield ModelEvent(
                        "text", "Verified source A only; source B remains unconfirmed."
                    )

    async def blocked(args, binding):
        raise ToolFinalizationRequired("BROWSER_SOURCE_UNAVAILABLE", 409)

    async def write(args, binding):
        effects.append(True)
        return {"ok": True}

    runtime = Runtime(store, ConversationModel(), worker_model=Worker())
    runtime.tools.directory = None
    runtime.tools.add(Tool("blocked_source", "Unavailable source", object_schema({}), blocked))
    runtime.tools.add(Tool("unexpected_write", "Write", object_schema({}), write, effect="write"))
    try:
        turn = await claimed_turn(runtime)
        if retries:
            with pytest.raises(DomainError, match="TOOL_FINALIZATION_STALLED"):
                await runtime.loop.run(turn, "worker")
        else:
            assert (
                await runtime.loop.run(turn, "worker")
                == "Verified source A only; source B remains unconfirmed."
            )
        assert effects == [] and rounds == 2
        manifests = await store.call(
            lambda db: rows(
                db,
                "SELECT parts_json FROM prompt_manifests WHERE turn_id=? ORDER BY attempt_no",
                (turn["id"],),
            )
        )
        first, closing = [json.loads(m["parts_json"]) for m in manifests]
        assert closing["historyView"] == "finalization"
        assert closing["requestBasis"] != first["requestBasis"]
    finally:
        await runtime.close()
