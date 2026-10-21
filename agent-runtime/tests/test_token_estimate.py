"""Context admission follows Pi's usage baseline and character fallback, never UTF-8 size."""

import asyncio
from dataclasses import replace

import pytest
from test_runtime import ConversationModel, until

from roami_agent.app import Runtime
from roami_agent.context.token_estimate import IMAGE_TOKENS, request_tokens, text_tokens
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


def test_multibyte_text_and_base64_images_are_not_counted_as_request_bytes():
    assert text_tokens("中" * 400) == text_tokens("a" * 400) == 100
    small = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:a"}}]}]
    large = [
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": "data:" + "a" * 100000}}],
        }
    ]
    assert request_tokens(small, []) == request_tokens(large, []) == IMAGE_TOKENS
    assert (
        request_tokens([{"role": "user", "content": "Hello"}], [{"description": "Tool " * 100}])
        > 100
    )


@pytest.mark.parametrize("invalidation", ["edit", "forget", "compact"])
async def test_context_reuses_actual_usage_adds_trailing_messages_and_invalidates_after_change(
    store,
    invalidation,
):
    class UsageModel(ConversationModel):
        async def stream(self, messages, tools):
            yield ModelEvent("text", "Acknowledged")
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 5000,
                    "outputTokens": 20,
                    "cacheReadTokens": 4000,
                },
            )

    runtime = Runtime(store, UsageModel(), settings=Settings(model="first"))
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "one", "Hello")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
        )
        before = await runtime.context.project("alice", c["id"])
        assert before["estimatedTokens"] == 5020
        assert before["usageTokens"] == 5020
        assert before["toolTokens"] > 0
        assert before["instructionTokens"] > 0
        runtime.supervisor.cancel()
        await asyncio.gather(runtime.supervisor, return_exceptions=True)
        runtime.supervisor = None
        # The newly appended text has no provider usage yet.
        await runtime.conversations.accept("alice", c["id"], "two", "追加问题" * 100)
        after = await runtime.context.project("alice", c["id"])
        assert after["usageTokens"] == 5020
        assert after["estimatedTokens"] == 5020 + text_tokens("追加问题" * 100)
        runtime.settings.current = replace(runtime.settings.current, model="second")
        changed = await runtime.context.project("alice", c["id"])
        assert changed["usageTokens"] == 0
        assert changed["estimatedTokens"] == (
            changed["historyTokens"] + changed["instructionTokens"] + changed["toolTokens"]
        )
        runtime.settings.current = replace(runtime.settings.current, model="first")
        if invalidation == "edit":
            await store.call(
                lambda db: db.execute(
                    "UPDATE messages SET content_json=json_set(content_json,'$.text','Edited history') WHERE id=?",
                    (receipt["messageId"],),
                ),
                write=True,
            )
        elif invalidation == "forget":
            memory = await runtime.memory.save("alice", "private", "Hello", receipt["messageId"])
            await runtime.memory.forget("alice", memory["id"])
        else:
            job = await runtime.context.request("alice", c["id"], "compact-usage")
            await runtime.context.run(job["id"])
            assert (await runtime.context.project("alice", c["id"]))["snapshotId"]
        assert (await runtime.context.project("alice", c["id"]))["usageTokens"] == 0
    finally:
        await runtime.close()


def test_context_window_has_no_application_cap_or_invented_default():
    assert Settings().context_window is None
    assert Settings().context_input_budget is None
    assert Settings(context_window=1_000_000).context_input_budget == 1_000_000


async def test_multibyte_input_is_admitted_by_token_budget_with_full_tools_counted(store):
    class CapturedModel(ConversationModel):
        def __init__(self):
            self.received = None

        async def stream(self, messages, tools):
            self.received = ([dict(message) for message in messages], list(tools))
            yield ModelEvent("text", "Received")

    model = CapturedModel()
    # Isolate admission from post-turn compaction as the default tool catalog grows.
    runtime = Runtime(store, model, settings=Settings(context_window=8000, compaction_ratio=0.99))
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        text = "界面布局测试" * 1000
        receipt = await runtime.chat.submit("alice", c["id"], "multibyte", text)
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
        )
        messages, tools = model.received
        assert messages[-1]["content"] == text
        assert tools
        assert request_tokens(messages, tools) < 8000
        assert (await runtime.context.project("alice", c["id"]))["snapshotId"] is None
    finally:
        await runtime.close()


async def test_tool_catalog_can_exhaust_context_even_when_user_message_is_small(store):
    class NeverCalled(ConversationModel):
        async def stream(self, messages, tools):
            pytest.fail("Oversized tools must be rejected before sending to the provider")
            yield ModelEvent("text", "unreachable")

    runtime = Runtime(store, NeverCalled(), settings=Settings(context_window=1000))
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "too-many-tools", "Hi")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='failed'", (receipt["turnId"],)
            ),
        )
        plan = await runtime.context.project("alice", c["id"])
        assert plan["historyTokens"] < 10
        assert plan["toolTokens"] > plan["inputBudget"]
        view = await runtime.conversations.messages("alice", c["id"])
        assert any(item.get("errorCode") == "CONTEXT_TOO_LARGE" for item in view["activities"])
    finally:
        await runtime.close()
