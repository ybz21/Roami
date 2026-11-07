import asyncio
import json

import pytest

from roami_agent.context.projection import Context, context_history, model_messages
from roami_agent.context.summary_input import summarize
from roami_agent.context.token_estimate import request_tokens
from roami_agent.conversation.transcript import Conversations
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row
from roami_agent.storage.transcript_repository import message


class BudgetModel:
    def __init__(self, budget=1200):
        self.budget = budget
        self.prompts = []
        self.gate = None
        self.started = asyncio.Event()
        self.fail_at = None

    async def stream(self, messages, tools):
        assert request_tokens(messages, tools) <= self.budget
        assert not tools
        self.prompts.append(messages)
        self.started.set()
        if self.gate:
            await self.gate.wait()
        if self.fail_at == len(self.prompts):
            raise DomainError("MODEL_HTTP_400", 502)
        yield ModelEvent(
            "text", "Keep original Main, task and provider. Evidence remains pending review."
        )


async def valid():
    return None


async def test_quoted_oversized_record_is_losslessly_segmented_with_running_summary():
    history = [{"role": "tool", "content": 'quote " and escape \\ 中文\n' * 700}]
    model = BudgetModel()
    result = await summarize(
        model,
        history,
        "Preserve identities",
        None,
        {"contextWindow": 1600, "compactionThreshold": 1200},
        valid,
    )
    assert result.startswith("Keep original Main")
    parts = [json.loads(p[1]["content"]) for p in model.prompts]
    assert len(parts) > 2
    assert "".join(p["historyFragment"] for p in parts) == encoded(history)
    cursor = 0
    for index, part in enumerate(parts):
        assert part["startCharacter"] == cursor
        cursor = part["endCharacter"]
        assert part["totalCharacters"] == len(encoded(history))
        assert part["focus"] == "Preserve identities"
        assert part["previousSummary"] == (result if index else "")
    assert cursor == len(encoded(history))


async def test_small_history_uses_one_original_structured_prompt():
    model = BudgetModel()
    history = [{"role": "user", "content": "Keep this request"}]
    await summarize(model, history, "focus", 100_000, {"contextWindow": 1600}, valid)
    data = json.loads(model.prompts[0][1]["content"])
    assert data == {"focus": "focus", "history": history}
    assert len(model.prompts) == 1
    assert "7500 tokens" in model.prompts[0][0]["content"]


class TokenizerMismatch:
    def __init__(self, actual_budget=500, *, reject_later=False, error="MODEL_CONTEXT_LIMIT"):
        self.actual_budget = actual_budget
        self.reject_later = reject_later
        self.error = error
        self.rejected = []
        self.accepted = []

    async def stream(self, messages, tools):
        data = json.loads(messages[1]["content"])
        late = self.reject_later and self.accepted and not self.rejected
        if request_tokens(messages, tools) > self.actual_budget or late:
            self.rejected.append(data)
            if late:
                self.actual_budget = request_tokens(messages, tools) // 2
            raise DomainError(self.error, 502)
        self.accepted.append(data)
        yield ModelEvent("text", "Keep the original Main and confirmed work.")


@pytest.mark.parametrize("configuration", [{}, {"contextWindow": 1600}])
async def test_provider_tokenizer_rejection_reduces_fragments_without_losing_history(configuration):
    history = [{"role": "tool", "content": '中文结果 "\\\n' * 1200}]
    model = TokenizerMismatch()
    assert await summarize(model, history, "retain evidence", None, configuration, valid)
    assert model.rejected and len(model.accepted) > 1
    assert "".join(item["historyFragment"] for item in model.accepted) == encoded(history)
    assert all(item["previousSummary"] for item in model.accepted[1:])


async def test_later_rejection_retries_same_position_and_preserves_successful_summary():
    history = [{"role": "tool", "content": "evidence " * 3000}]
    model = TokenizerMismatch(1200, reject_later=True)
    await summarize(model, history, "", None, {"contextWindow": 1200}, valid)
    rejected = model.rejected[0]
    retried = next(
        item for item in model.accepted if item["startCharacter"] == rejected["startCharacter"]
    )
    assert retried["previousSummary"] == rejected["previousSummary"]
    assert retried["endCharacter"] < rejected["endCharacter"]
    assert "".join(item["historyFragment"] for item in model.accepted) == encoded(history)


async def test_other_bad_requests_are_not_retried_as_context_rejection():
    model = TokenizerMismatch(0, error="MODEL_HTTP_400")
    with pytest.raises(DomainError, match="^MODEL_HTTP_400$"):
        await summarize(model, [{"role": "user", "content": "unchanged"}], "", None, {}, valid)
    assert len(model.rejected) == 1 and not model.accepted


async def test_cancel_between_rejection_and_retry_sends_no_more_requests():
    model = TokenizerMismatch(0)

    async def validate():
        if model.rejected:
            raise DomainError("COMPACTION_CANCELLED", 409)

    with pytest.raises(DomainError, match="^COMPACTION_CANCELLED$"):
        await summarize(
            model, [{"role": "user", "content": "evidence " * 400}], "", None, {}, validate
        )
    assert len(model.rejected) == 1 and not model.accepted


async def test_impossible_provider_budget_fails_without_looping_or_omitting_history():
    model = TokenizerMismatch(0)
    with pytest.raises(DomainError, match="^COMPACTION_INPUT_BUDGET_TOO_SMALL$"):
        await summarize(
            model, [{"role": "user", "content": "evidence " * 1000}], "", None, {}, valid
        )
    assert 1 < len(model.rejected) < 20
    assert not model.accepted


async def test_focus_that_cannot_fit_fails_before_model_call():
    model = BudgetModel(50)
    with pytest.raises(DomainError, match="COMPACTION_INPUT_BUDGET_TOO_SMALL"):
        await summarize(
            model,
            [{"role": "user", "content": "large" * 2000}],
            "focus" * 300,
            None,
            {"contextWindow": 50},
            valid,
        )
    assert not model.prompts


async def large_conversation(store):
    conversations = Conversations(store)
    c = await conversations.create("alice")
    for index in range(3):
        receipt = await conversations.accept(
            "alice", c["id"], str(index), "historical details " * 1500
        )

        def finish(db, receipt=receipt):
            message(
                db,
                c["id"],
                c["active_branch_id"],
                "assistant",
                {"text": "Deliverable pending review. " * 1000},
                turn_id=receipt["turnId"],
            )
            db.execute("UPDATE turns SET state='completed' WHERE id=?", (receipt["turnId"],))

        await store.call(finish, write=True)
    return c


def configure(context):
    context.request_context = lambda: {
        "contextWindow": 1600,
        "compactionThreshold": 1200,
        "instructions": "",
        "catalog": [],
    }


async def test_multiple_model_windows_activate_one_snapshot_without_rewriting_history(store):
    c = await large_conversation(store)
    before = await Conversations(store).messages("alice", c["id"])
    model = BudgetModel()
    context = Context(store, model, keep_recent_tokens=500)
    configure(context)
    job = await context.request("alice", c["id"], "large-compact")
    await context.run(job["id"])
    state = await context.compaction("alice", c["id"], job["id"])
    assert state["state"] == "completed"
    assert len(model.prompts) > 1
    assert (await context.project("alice", c["id"]))["snapshotId"] == state["snapshotId"]
    assert (await Conversations(store).messages("alice", c["id"]))["messages"] == before["messages"]
    source = await store.call(lambda db: model_messages(context_history(db, c["active_branch_id"])))
    serialized = "".join(json.loads(p[1]["content"])["historyFragment"] for p in model.prompts)
    assert serialized == encoded(source)


async def test_late_provider_rejection_still_activates_one_complete_snapshot(store):
    c = await large_conversation(store)
    before = await Conversations(store).messages("alice", c["id"])
    model = TokenizerMismatch(1200, reject_later=True)
    context = Context(store, model, keep_recent_tokens=500)
    configure(context)
    job = await context.request("alice", c["id"], "provider-retry")
    await context.run(job["id"])
    state = await context.compaction("alice", c["id"], job["id"])
    assert state["state"] == "completed" and model.rejected
    assert (await Conversations(store).messages("alice", c["id"]))["messages"] == before["messages"]
    source = await store.call(lambda db: model_messages(context_history(db, c["active_branch_id"])))
    assert "".join(item["historyFragment"] for item in model.accepted) == encoded(source)
    assert (await store.call(lambda db: row(db, "SELECT COUNT(*) AS n FROM context_snapshots")))[
        "n"
    ] == 1
    assert (await context.project("alice", c["id"]))["snapshotId"] == state["snapshotId"]


@pytest.mark.parametrize("action", ["cancel", "memory"])
async def test_cancel_or_source_change_stops_before_next_segment(store, action):
    c = await large_conversation(store)
    model = BudgetModel()
    model.gate = asyncio.Event()
    context = Context(store, model, keep_recent_tokens=500)
    configure(context)
    job = await context.request("alice", c["id"], "interrupted-compact")
    task = asyncio.create_task(context.run(job["id"]))
    await model.started.wait()
    if action == "cancel":
        await context.cancel("alice", c["id"], job["id"])
    else:
        await store.call(
            lambda db: db.execute("UPDATE owner_versions SET memory_epoch=memory_epoch+1"),
            write=True,
        )
    model.gate.set()
    await task
    assert len(model.prompts) == 1
    assert not (await context.project("alice", c["id"]))["snapshotId"]
    state = await context.compaction("alice", c["id"], job["id"])
    assert state["state"] == ("cancelled" if action == "cancel" else "failed")


async def test_middle_failure_leaves_history_and_retry_can_finish(store):
    c = await large_conversation(store)
    before = await Conversations(store).messages("alice", c["id"])
    model = BudgetModel()
    model.fail_at = 2
    context = Context(store, model, keep_recent_tokens=500)
    configure(context)
    job = await context.request("alice", c["id"], "failed-compact")
    await context.run(job["id"])
    state = await context.compaction("alice", c["id"], job["id"])
    assert state["error"] == "MODEL_HTTP_400"
    assert not (await context.project("alice", c["id"]))["snapshotId"]
    assert (await Conversations(store).messages("alice", c["id"]))["messages"] == before["messages"]
    assert (await store.call(lambda db: row(db, "SELECT COUNT(*) AS n FROM context_snapshots")))[
        "n"
    ] == 0
    model.fail_at = None
    retry = await context.request("alice", c["id"], "retry-compact")
    await context.run(retry["id"])
    assert (await context.compaction("alice", c["id"], retry["id"]))["state"] == "completed"
