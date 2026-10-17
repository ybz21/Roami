import asyncio
import json

import httpx
import pytest

from roami_agent.context import Context
from roami_agent.conversation import Conversations, message
from roami_agent.providers import ChatCompletions, ModelEvent
from roami_agent.storage import DomainError, row


class SummaryModel:
    model = "test-summary"

    def __init__(self):
        self.gate = None
        self.started = asyncio.Event()

    async def stream(self, messages, tools):
        self.started.set()
        if self.gate:
            await self.gate.wait()
        yield ModelEvent("text", "Goal: implement Agent. Decision: Python. Pending: tests.")


async def completed_conversation(store):
    conversations = Conversations(store)
    c = await conversations.create("alice")
    for index in range(6):
        receipt = await conversations.accept("alice", c["id"], str(index), "question " * 50)

        def finish(db, receipt=receipt):
            message(
                db,
                c["id"],
                c["active_branch_id"],
                "assistant",
                {"text": "answer " * 50},
                turn_id=receipt["turnId"],
            )
            db.execute("UPDATE turns SET state='completed' WHERE id=?", (receipt["turnId"],))

        await store.call(finish, write=True)
    return c


async def test_compaction_persists_summary_preserves_transcript_and_appends(store):
    c = await completed_conversation(store)
    model = SummaryModel()
    context = Context(store, model)
    before = await Conversations(store).messages("alice", c["id"])
    original = await context.project("alice", c["id"])
    job = await context.request("alice", c["id"], "compact-one", "preserve decisions")
    retry = await context.request("alice", c["id"], "compact-one", "preserve decisions")
    assert job["id"] == retry["id"]
    await context.run(job["id"])
    projected = await context.project("alice", c["id"])
    assert projected["snapshotId"]
    assert projected["estimatedTokens"] < original["estimatedTokens"]
    assert len(projected["messages"]) == 7
    assert (await Conversations(store).messages("alice", c["id"]))["messages"] == before["messages"]
    await Conversations(store).accept("alice", c["id"], "new", "new message after compact")
    assert (await context.project("alice", c["id"]))["messages"][-1][
        "content"
    ] == "new message after compact"


async def test_cancelled_or_invalidated_compaction_does_not_activate(store):
    c = await completed_conversation(store)
    model = SummaryModel()
    model.gate = asyncio.Event()
    context = Context(store, model)
    job = await context.request("alice", c["id"], "compact")
    task = asyncio.create_task(context.run(job["id"]))
    await model.started.wait()
    await context.cancel("alice", c["id"], job["id"])
    model.gate.set()
    await task
    assert not (await context.project("alice", c["id"]))["snapshotId"]
    state = await store.call(lambda db: row(db, "SELECT * FROM jobs WHERE id=?", (job["id"],)))
    assert json.loads(state["payload_json"])["state"] == "cancelled"

    model.started.clear()
    model.gate.clear()
    job = await context.request("alice", c["id"], "compact-again")
    task = asyncio.create_task(context.run(job["id"]))
    await model.started.wait()
    await store.call(
        lambda db: db.execute("UPDATE owner_versions SET memory_epoch=memory_epoch+1"), write=True
    )
    model.gate.set()
    await task
    assert not (await context.project("alice", c["id"]))["snapshotId"]
    state = await store.call(lambda db: row(db, "SELECT * FROM jobs WHERE id=?", (job["id"],)))
    assert json.loads(state["payload_json"])["error"] == "COMPACTION_SOURCE_CHANGED"


async def test_context_of_turn_does_not_include_later_user_messages(store):
    conversations = Conversations(store)
    c = await conversations.create("alice")
    first = await conversations.accept("alice", c["id"], "one", "first")
    await conversations.accept("alice", c["id"], "two", "later")
    plan = await Context(store, SummaryModel()).project(
        "alice", c["id"], through_turn=first["turnId"]
    )
    assert [m["content"] for m in plan["messages"]] == ["first"]


async def test_provider_stream_tool_fragments_and_usage():
    payloads = [
        {"choices": [{"delta": {"content": "Let me check"}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call1",
                                "function": {"name": "status", "arguments": "{"},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "}"}}]},
                    "finish_reason": "tool_calls",
                }
            ]
        },
        {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 4}},
    ]

    async def handle(request):
        body = json.loads(request.content)
        assert body["stream"]
        return httpx.Response(
            200,
            text="".join("data: " + json.dumps(p) + "\n\n" for p in payloads) + "data: [DONE]\n\n",
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    provider = ChatCompletions("https://model.invalid/v1", "test", client=client)
    result = [e async for e in provider.stream([{"role": "user", "content": "Hi"}], [])]
    assert [e.kind for e in result] == ["text", "usage", "tool"]
    assert result[-1].value["function"]["arguments"] == "{}"
    await provider.close()


async def test_provider_rejects_partial_response():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            )
        )
    )
    provider = ChatCompletions("https://model.invalid/v1", "test", client=client)
    with pytest.raises(DomainError, match="MODEL_STREAM_INCOMPLETE"):
        _ = [e async for e in provider.stream([], [])]
    await provider.close()
