"""A 75% soft trigger schedules compaction without changing the hard admission limit."""

import json

import pytest

from roami_agent.app import Runtime
from roami_agent.context.projection import Context
from roami_agent.context.prompt_builder import PromptBuilder
from roami_agent.conversation.transcript import Conversations
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


class SummaryModel:
    model = "threshold-test"

    def __init__(self):
        self.summaries = 0

    async def stream(self, messages, tools):
        self.summaries += 1
        yield ModelEvent("text", "Confirmed decisions retained.")


def test_threshold_follows_model_window_without_application_cap_or_output_reserve():
    assert Settings().compaction_threshold is None
    assert Settings(context_window=1_000_000).compaction_threshold == 750_000
    assert Settings(context_window=32_000).compaction_threshold == 24_000
    assert Settings(context_window=32_000, reserve_tokens=16_000).compaction_threshold == 24_000


@pytest.mark.parametrize("ratio", [0, 1, -0.1, True, "0.75"])
def test_invalid_ratio_is_rejected_when_loading_configuration(tmp_path, ratio):
    path = tmp_path / "agent.toml"
    literal = json.dumps(ratio)
    path.write_text("[runtime]\ncompaction_ratio=" + literal + "\n")
    with pytest.raises(DomainError, match="INVALID_RUNTIME_CONFIG"):
        Settings.load(path)


async def test_soft_threshold_compacts_history_before_hard_limit(store):
    from test_context_provider import completed_conversation

    c = await completed_conversation(store)
    conversations = Conversations(store)
    receipt = await conversations.accept("alice", c["id"], "soft", "new input " * 150)
    settings = Settings(context_window=1600)
    model = SummaryModel()
    context = Context(store, model)
    before = await context.project("alice", c["id"])
    assert settings.compaction_threshold < before["estimatedTokens"] < settings.context_input_budget
    turn = await store.call(
        lambda db: dict(
            row(db, "SELECT * FROM turns WHERE id=?", (receipt["turnId"],)), owner_id="alice"
        )
    )
    plan, prompt = await PromptBuilder(store, context, settings).build(turn, "", [], None)
    assert plan["snapshotId"]
    assert plan["estimatedTokens"] < settings.compaction_threshold
    assert model.summaries == 1
    assert len((await conversations.messages("alice", c["id"]))["messages"]) == 13
    assert prompt[-1]["content"] == "new input " * 150


@pytest.mark.parametrize("length,admitted", [(3200, True), (4400, False)])
async def test_current_input_above_soft_trigger_keeps_hard_limit_semantics(store, length, admitted):
    conversations = Conversations(store)
    c = await conversations.create("alice")
    receipt = await conversations.accept("alice", c["id"], "current-only", "a" * length)
    turn = await store.call(
        lambda db: dict(
            row(db, "SELECT * FROM turns WHERE id=?", (receipt["turnId"],)), owner_id="alice"
        )
    )
    settings, model = Settings(context_window=1000), SummaryModel()
    builder = PromptBuilder(store, Context(store, model), settings)
    if admitted:
        plan, _ = await builder.build(turn, "", [], None)
        assert (
            settings.compaction_threshold < plan["estimatedTokens"] < settings.context_input_budget
        )
    else:
        with pytest.raises(DomainError, match="CONTEXT_TOO_LARGE"):
            await builder.build(turn, "", [], None)
    assert model.summaries == 0
    assert (await conversations.messages("alice", c["id"]))["messages"][0]["content"][
        "text"
    ] == "a" * length


@pytest.mark.parametrize(
    "window,used,queued",
    [
        (24000, 17999, False),
        (24000, 18000, True),
        (24000, 18001, True),
        (1000000, 749999, False),
        (1000000, 750000, True),
        (1000000, 750001, True),
    ],
)
async def test_final_usage_schedules_compaction_after_reply_without_running_summary_inline(
    store, window, used, queued
):
    class UsageModel:
        model = "after-reply"
        calls = 0

        async def stream(self, messages, tools):
            self.calls += 1
            yield ModelEvent("text", "Reply delivered")
            yield ModelEvent("usage", {"inputTokens": used - 10, "outputTokens": 10})

    model = UsageModel()
    runtime = Runtime(store, model, settings=Settings(context_window=window))
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "finish", "Small input")
        job = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?",
                (receipt["turnId"],),
            )
        )
        turn = await runtime.mailbox.claim(job)
        await runtime.loop.run(turn, "main")
        assert (
            await store.call(
                lambda db: row(db, "SELECT state FROM turns WHERE id=?", (turn["id"],))
            )
        )["state"] == "completed"
        compact = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE kind='context.compact' AND json_extract(payload_json,'$.conversationId')=?",
                (c["id"],),
            )
        )
        assert bool(compact) == queued
        assert model.calls == 1
        if compact:
            assert compact["state"] == "queued"
            assert json.loads(compact["payload_json"])["targetTokens"] < window * 0.75
            preview = await runtime.context.project("alice", c["id"])
            assert preview["compactionThreshold"] == int(window * 0.75)
            assert preview["capacityBasis"] == "model_window"
    finally:
        await runtime.close()


def test_legacy_input_budget_does_not_cap_a_million_token_model(tmp_path):
    path = tmp_path / "agent.toml"
    path.write_text("[model]\ncontext_window=1000000\n[runtime]\ninput_budget=24000\n")
    settings = Settings.load(path)
    assert settings.context_input_budget == 1_000_000
    assert settings.compaction_threshold == 750_000


async def test_unknown_window_does_not_compact_at_an_invented_capacity(store):
    conversations = Conversations(store)
    c = await conversations.create("alice")
    receipt = await conversations.accept("alice", c["id"], "no-cap", "a" * 100000)
    turn = await store.call(
        lambda db: dict(
            row(db, "SELECT * FROM turns WHERE id=?", (receipt["turnId"],)), owner_id="alice"
        )
    )
    model = SummaryModel()
    plan, prompt = await PromptBuilder(store, Context(store, model), Settings()).build(
        turn, "", [], None
    )
    assert plan["estimatedTokens"] > 24000
    assert plan["contextWindow"] is None and plan["compactionThreshold"] is None
    assert plan["capacityBasis"] == "unknown" and model.summaries == 0
    assert prompt[-1]["content"] == "a" * 100000
