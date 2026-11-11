"""Final tool transport preserves model values without publishing unsubmitted drafts."""

import json

import pytest
from test_argument_repair_progress import claimed_turn
from test_foundations import call

from roami_agent.app import Runtime
from roami_agent.conversation.activity_payloads import activity_payload
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.database import rows


class ReplyModel:
    model = "final-reply-protocol-fixture"

    def __init__(self, replies):
        self.replies, self.calls = replies, 0

    async def stream(self, messages, tools):
        item = self.replies[self.calls]
        self.calls += 1
        if isinstance(item, str):
            yield ModelEvent("text", item)
        else:
            yield ModelEvent("text", "Unsubmitted preamble")
            yield ModelEvent("tool", call(item[0], item[1]))
        yield ModelEvent("usage", {"input_tokens": 7, "output_tokens": 3})


@pytest.mark.parametrize("text", ["Ordinary final answer", '<reply>{"enabled": false}</reply>'])
async def test_plain_final_is_delivered_through_reply_without_transport_rejection(store, text):
    model = ReplyModel([text])
    runtime = Runtime(store, model, require_final_tool=True)
    try:
        turn = await claimed_turn(runtime)
        assert await runtime.loop.run(turn, "main") == text
        assert model.calls == 1
        events = await runtime.conversations.events("alice", turn["conversation_id"])
        assert [e["payload"]["text"] for e in events if e["kind"] == "message.delta"] == [text]
        receipts = await store.call(
            lambda db: rows(
                db,
                "SELECT x.state,m.content_json FROM tool_calls x JOIN messages m "
                "ON m.id=x.result_message_id WHERE x.turn_id=?",
                (turn["id"],),
            )
        )
        assert [item["state"] for item in receipts] == ["succeeded"]
        assert json.loads(json.loads(receipts[0]["content_json"])["text"]) == {"accepted": True}
        snapshot = await runtime.conversations.messages("alice", turn["conversation_id"])
        activity = next(item for item in snapshot["activities"] if item["name"] == "reply")
        assert activity["preview"]["output"] is None
        detail = await store.call(
            lambda db: activity_payload(db, "alice", turn["conversation_id"], activity["id"])
        )
        assert detail["output"] is None
    finally:
        await runtime.close()


async def test_explicit_text_submission_keeps_requested_markup_unchanged(store):
    text = "<reply>Requested XML & literal text</reply>"
    model = ReplyModel([("reply", {"text": text})])
    runtime = Runtime(store, model, require_final_tool=True)
    try:
        assert await runtime.loop.run(await claimed_turn(runtime), "main") == text
        assert model.calls == 1
    finally:
        await runtime.close()


async def test_invalid_plain_final_still_uses_existing_argument_repair(store):
    model = ReplyModel(["Let me know if you need help", "Let me know if you need help"])
    runtime = Runtime(store, model, require_final_tool=True)
    try:
        turn = await claimed_turn(runtime)
        with pytest.raises(DomainError, match="TOOL_ARGUMENT_REPAIR_STALLED"):
            await runtime.loop.run(turn, "main")
        assert model.calls == 2
        events = await runtime.conversations.events("alice", turn["conversation_id"])
        assert not any(e["kind"] in {"message.delta", "message.completed"} for e in events)
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "value", [{"s": "a\nb", "b": True}, [1, "two", None], None, False, 12, "value"]
)
async def test_json_submission_preserves_json_values_and_types(store, value):
    runtime = Runtime(store, ReplyModel([]))
    try:
        result = await runtime.tools.invoke(call("reply", {"json": value}), "main", {})
        assert json.loads(result["reply"]) == value
        assert type(json.loads(result["reply"])) is type(value)
    finally:
        await runtime.close()


@pytest.mark.parametrize("arguments", [{}, {"text": "one", "json": {}}, {"json": float("nan")}])
async def test_reply_requires_one_finite_transport_value(store, arguments):
    runtime = Runtime(store, ReplyModel([]))
    try:
        with pytest.raises(DomainError, match="INVALID_TOOL_ARGUMENTS"):
            await runtime.tools.invoke(call("reply", arguments), "main", {})
    finally:
        await runtime.close()


async def test_worker_keeps_plain_text_completion(store):
    model = ReplyModel(["Worker result"])
    runtime = Runtime(store, model, require_final_tool=True)
    try:
        assert await runtime.loop.run(await claimed_turn(runtime), "worker") == "Worker result"
        assert model.calls == 1
    finally:
        await runtime.close()


async def test_question_still_ends_the_turn_without_a_reply(store):
    model = ReplyModel([("ask_user", {"prompt": "Which target?", "options": ["First", "Second"]})])
    runtime = Runtime(store, model, require_final_tool=True)
    try:
        turn = await claimed_turn(runtime)
        assert await runtime.loop.run(turn, "main") == ""
        events = await runtime.conversations.events("alice", turn["conversation_id"])
        completed = [e for e in events if e["kind"] == "message.completed"]
        assert (
            len(completed) == 1 and completed[0]["payload"]["question"]["prompt"] == "Which target?"
        )
        assert model.calls == 1
    finally:
        await runtime.close()


async def test_plain_final_still_passes_content_review(store):
    from roami_agent.replies.source_review import REVIEW_INSTRUCTIONS

    value = {"label": "original text", "enabled": False}

    class AcceptingReviewer(ReplyModel):
        def __init__(self):
            super().__init__(["<reply>invalid transport</reply>", ("reply", {"json": value})])
            self.reviews, self.readings = 0, 0

        async def stream(self, messages, tools):
            if messages[0]["content"] == REVIEW_INSTRUCTIONS:
                self.reviews += 1
                yield ModelEvent(
                    "tool", call("source_review_verdict", {"accepted": True, "feedback": ""})
                )
            elif not tools:
                self.readings += 1
                yield ModelEvent("text", json.dumps(value))
            else:
                async for part in super().stream(messages, tools):
                    yield part

    model = AcceptingReviewer()
    runtime = Runtime(store, model, review_replies=True, require_final_tool=True)
    try:
        turn = await claimed_turn(runtime)
        assert await runtime.loop.run(turn, "main") == "<reply>invalid transport</reply>"
        assert model.calls == 1 and model.reviews == 1 and model.readings == 0
        events = await runtime.conversations.events("alice", turn["conversation_id"])
        assert [e["payload"]["text"] for e in events if e["kind"] == "message.delta"] == [
            "<reply>invalid transport</reply>"
        ]
    finally:
        await runtime.close()
