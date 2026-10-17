import asyncio
import json

import pytest

from roami_agent.app import Runtime
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.database import row


class ConversationModel:
    model = "injected-model"

    async def stream(self, messages, tools):
        if messages[-1]["role"] == "tool":
            yield ModelEvent("text", "Task delegated; you can keep chatting.")
        elif messages[-1]["content"].startswith("Background task result"):
            yield ModelEvent("text", "Your background research is complete.")
        elif messages[-1]["content"] == "delegate research":
            yield ModelEvent(
                "tool",
                {
                    "id": "delegate-call",
                    "type": "function",
                    "function": {
                        "name": "delegate",
                        "arguments": json.dumps({"goal": "Research the topic"}),
                    },
                },
            )
        else:
            yield ModelEvent("text", "Answer: " + messages[-1]["content"])
        yield ModelEvent("usage", {"input_tokens": 10, "output_tokens": 5})


async def until(store, predicate, *, timeout=5):
    async with asyncio.timeout(timeout):
        while not await store.call(predicate):
            await asyncio.sleep(0.01)


async def test_runtime_streams_committed_reply_and_usage(store):
    runtime = Runtime(store, ConversationModel())
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        result = await runtime.chat.submit("alice", c["id"], "one", "hello")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (result["turnId"],)
            ),
        )
        view = await runtime.conversations.messages("alice", c["id"])
        assert view["messages"][-1]["content"]["text"] == "Answer: hello"
        events = await runtime.conversations.events("alice", c["id"])
        assert [e["kind"] for e in events][-3:] == [
            "message.started",
            "message.delta",
            "message.completed",
        ]
        usage = await store.call(
            lambda db: row(
                db, "SELECT usage_json FROM prompt_manifests WHERE turn_id=?", (result["turnId"],)
            )
        )
        assert json.loads(usage["usage_json"])["input_tokens"] == 10
    finally:
        await runtime.close()


async def test_delegation_runs_child_then_reports_to_original_conversation(store):
    runtime = Runtime(store, ConversationModel())
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        await runtime.chat.submit("alice", c["id"], "one", "delegate research")
        await until(
            store,
            lambda db: (
                db.execute(
                    "SELECT COUNT(*) FROM turns WHERE trigger_kind='completion' AND state='completed'"
                ).fetchone()[0]
                == 1
            ),
        )
        tasks = await runtime.tasks.list("alice", c["id"])
        assert len(tasks) == 1
        assert tasks[0]["state"] == "succeeded"
        original = await runtime.conversations.messages("alice", c["id"])
        assert (
            original["messages"][-1]["content"]["text"] == "Your background research is complete."
        )
        assert sum(m["role"] == "tool" for m in original["messages"]) == 1
    finally:
        await runtime.close()


class GatedModel:
    model = "injected-gated"

    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.prompts = []

    async def stream(self, messages, tools):
        self.prompts.append(json.loads(json.dumps(messages)))
        if len(self.prompts) == 1:
            yield ModelEvent("text", "partial " * 200)
            self.entered.set()
            await self.release.wait()
            yield ModelEvent("text", "first answer")
        else:
            yield ModelEvent("text", "second answer")


async def test_queued_turn_context_preserves_previous_reply_without_future_input(store):
    class EmptyMemoryModel:
        model = "memory-fixture"

        async def stream(self, messages, tools):
            yield ModelEvent("text", '{"memories":[]}')

    model = GatedModel()
    runtime = Runtime(store, model, memory_model=EmptyMemoryModel())
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        await runtime.chat.submit("alice", c["id"], "one", "first question")
        await model.entered.wait()
        second = await runtime.chat.submit("alice", c["id"], "two", "second question")
        model.release.set()
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (second["turnId"],)
            ),
        )
        assert "second question" not in json.dumps(model.prompts[0])
        assert "first answer" in json.dumps(model.prompts[1])
        assert model.prompts[1][-1]["content"] == "second question"
    finally:
        await runtime.close()


async def test_stop_keeps_partial_and_idempotent_target(store):
    model = GatedModel()
    runtime = Runtime(store, model)
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        first = await runtime.chat.submit("alice", c["id"], "one", "first question")
        await model.entered.wait()
        receipt = await runtime.chat.submit("alice", c["id"], "stop-one", "/stop")
        assert receipt["turnId"] == first["turnId"]
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='interrupted'", (first["turnId"],)
            ),
        )
        second = await runtime.chat.submit("alice", c["id"], "two", "second question")
        await runtime.chat.submit("alice", c["id"], "stop-one", "/stop")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (second["turnId"],)
            ),
        )
        view = await runtime.conversations.messages("alice", c["id"])
        assert any(
            m["status"] == "interrupted" and m["content"]["text"].startswith("partial")
            for m in view["messages"]
        )
    finally:
        await runtime.close()


class NestedModel(ConversationModel):
    def __init__(self):
        self.leaf_started = asyncio.Event()
        self.leaf_release = asyncio.Event()
        self.completions = []

    async def stream(self, messages, tools):
        last = messages[-1]
        if last["role"] == "tool":
            yield ModelEvent("text", "Delegated; awaiting descendants.")
        elif last["content"] == "root":
            yield ModelEvent(
                "tool",
                {
                    "id": "root-delegate",
                    "type": "function",
                    "function": {"name": "delegate", "arguments": json.dumps({"goal": "parent"})},
                },
            )
        elif last["content"] == "parent":
            yield ModelEvent(
                "tool",
                {
                    "id": "child-delegate",
                    "type": "function",
                    "function": {"name": "delegate", "arguments": json.dumps({"goal": "leaf"})},
                },
            )
        elif last["content"] == "leaf":
            self.leaf_started.set()
            await self.leaf_release.wait()
            yield ModelEvent("text", "Leaf evidence.")
        elif last["content"].startswith("Background task result"):
            self.completions.append(last["content"])
            yield ModelEvent("text", "All delegated work is joined.")
        else:
            yield ModelEvent("text", "Quick answer.")


async def test_nested_delegation_joins_descendants_and_reserves_main_capacity(store):
    from roami_agent.server.configuration import Settings

    model = NestedModel()
    runtime = Runtime(store, model, settings=Settings(workers=1))
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        await runtime.chat.submit("alice", c["id"], "one", "root")
        await asyncio.wait_for(model.leaf_started.wait(), 5)
        parent = (await runtime.tasks.list("alice", c["id"]))[0]
        assert parent["state"] == "verifying"
        quick = await runtime.chat.submit("alice", c["id"], "two", "quick question")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (quick["turnId"],)
            ),
        )
        assert not model.leaf_release.is_set()
        model.leaf_release.set()
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE trigger_kind='completion' AND state='completed'"
            ),
        )
        task_list = await runtime.tasks.list("alice")
        assert len(task_list) == 2
        assert {t["state"] for t in task_list} == {"succeeded"}
        assert "Leaf evidence" in model.completions[0]
        parent = next(t for t in task_list if t["parent_task_id"] is None)
        assert json.loads(parent["budget_json"])["usedSteps"] == 3
    finally:
        model.leaf_release.set()
        await runtime.close()


async def test_runtime_automatically_compacts_before_oversized_model_input(store):
    from test_context_provider import completed_conversation

    from roami_agent.server.configuration import Settings

    class CompactingModel(ConversationModel):
        async def stream(self, messages, tools):
            if messages[0]["content"].startswith("Summarize"):
                yield ModelEvent("text", "Goal: retain earlier confirmed decisions.")
            else:
                async for item in super().stream(messages, tools):
                    yield item

    c = await completed_conversation(store)
    runtime = Runtime(store, CompactingModel(), settings=Settings(input_budget=6000))
    await runtime.start()
    try:
        receipt = await runtime.chat.submit(
            "alice", c["id"], "trigger", "Trigger automatic compaction"
        )
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
        )
        plan = await runtime.context.project("alice", c["id"])
        assert plan["snapshotId"]
        messages = (await runtime.conversations.messages("alice", c["id"]))["messages"]
        assert len(messages) == 14
        assert messages[-1]["content"]["text"].startswith("Answer:")
    finally:
        await runtime.close()


@pytest.mark.parametrize("with_snapshot", [False, True])
async def test_completion_evidence_stays_before_its_tool_round_after_context_rebuild(
    store, with_snapshot
):
    class CompletionToolsModel:
        model = "completion-order-fixture"

        def __init__(self):
            self.main_prompts = []

        async def stream(self, messages, tools):
            if messages[0]["content"].startswith("Summarize"):
                yield ModelEvent("text", "Retain prior confirmed decisions.")
                return
            if any(tool["function"]["name"] == "shell" for tool in tools):
                yield ModelEvent("text", "Worker evidence")
                return
            self.main_prompts.append(json.loads(json.dumps(messages)))
            if len(self.main_prompts) == 1:
                yield ModelEvent(
                    "tool",
                    {
                        "id": "completion-memory",
                        "function": {
                            "name": "memory_search",
                            "arguments": '{"query":"prior decisions"}',
                        },
                    },
                )
            else:
                yield ModelEvent("text", "Reported verified evidence")

    model = CompletionToolsModel()
    runtime = Runtime(store, model, memory_model=ConversationModel())
    await runtime.start()
    try:
        if with_snapshot:
            from test_context_provider import completed_conversation

            conversation = await completed_conversation(store)
            operation = await runtime.context.request("alice", conversation["id"], "snapshot")
            await runtime.context.run(operation["id"])
            assert (await runtime.context.project("alice", conversation["id"]))["snapshotId"]
        else:
            conversation = await runtime.conversations.create("alice")
        await runtime.tasks.create(
            "alice", conversation["id"], "Research", key="completion-order", record_intent=True
        )
        runtime.wakeup.set()
        await until(
            store,
            lambda db: row(
                db,
                "SELECT id FROM turns WHERE conversation_id=? AND trigger_kind='completion' AND state='completed'",
                (conversation["id"],),
            ),
        )
        assert len(model.main_prompts) == 2
        second = model.main_prompts[1]
        evidence = next(
            index
            for index, message in enumerate(second)
            if message["content"].startswith("Background task result")
        )
        call = next(index for index, message in enumerate(second) if message.get("tool_calls"))
        result = next(index for index, message in enumerate(second) if message["role"] == "tool")
        assert evidence < call < result
        assert second[-1]["role"] == "tool"
        assert (
            sum(message["content"].startswith("Background task result") for message in second) == 1
        )
    finally:
        await runtime.close()


async def test_provider_tool_ids_are_scoped_to_the_turn_for_delegation(store):
    runtime = Runtime(store, ConversationModel())
    try:
        await runtime.start()
        first = await runtime.conversations.create("alice")
        second = await runtime.conversations.create("alice")
        for conversation in (first, second):
            await runtime.chat.submit(
                "alice", conversation["id"], "request-" + conversation["id"], "delegate research"
            )
        await until(store, lambda db: db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 2)
        tasks = await runtime.tasks.list("alice")
        assert {task["origin_conversation_id"] for task in tasks} == {first["id"], second["id"]}
        assert len({task["intent_json"] for task in tasks}) == 2
    finally:
        await runtime.close()
