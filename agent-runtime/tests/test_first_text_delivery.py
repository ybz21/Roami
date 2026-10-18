import asyncio
import json

import pytest

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent


async def test_first_text_is_durable_before_the_provider_continues(store):
    release = asyncio.Event()

    class PausedProvider:
        model = "paused-provider"

        async def stream(self, messages, tools):
            yield ModelEvent("text", "first")
            await release.wait()
            yield ModelEvent("text", " second")

    runtime = Runtime(store, PausedProvider())
    runtime.loop.clock = lambda: 0
    try:
        await runtime.start()
        conversation = await runtime.conversations.create("local")
        receipt = await runtime.chat.submit("local", conversation["id"], "first-text", "hello")
        async with asyncio.timeout(2):
            while True:
                events = await runtime.conversations.events("local", conversation["id"])
                deltas = [event for event in events if event["kind"] == "message.delta"]
                if deltas:
                    break
                await asyncio.sleep(0.01)
        assert deltas[0]["payload"]["text"] == "first"
        assert not release.is_set()
        snapshot = await runtime.conversations.messages("local", conversation["id"])
        assert any(
            turn["id"] == receipt["turnId"] and turn["state"] == "running"
            for turn in snapshot["turns"]
        )
    finally:
        release.set()
        await runtime.close()


async def test_delegate_wire_contract_rejects_invented_target_kinds(store):
    runtime = Runtime(store, None)
    try:
        call = {
            "id": "routing",
            "function": {
                "name": "delegate",
                "arguments": json.dumps(
                    {"goal": "work", "target": {"kind": "session", "sessionId": "observed-id"}}
                ),
            },
        }
        _, args = runtime.tools.validate(call, "main")
        assert args["target"]["sessionId"] == "observed-id"
        call["function"]["arguments"] = json.dumps(
            {"goal": "work", "target": {"kind": "existing_session", "sessionId": "observed-id"}}
        )
        with pytest.raises(DomainError):
            runtime.tools.validate(call, "main")
        assert (
            await store.call(lambda db: db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]) == 0
        )
    finally:
        await runtime.close()
