"""Real argument increments remain provisional until the source reviewer accepts."""

import asyncio
import json

import pytest
from test_argument_repair_progress import claimed_turn
from test_foundations import call

from roami_agent.app import Runtime
from roami_agent.context.projection import context_history, model_messages
from roami_agent.memory.writer import source_snapshot
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.replies.source_review import VERDICT_TOOL


class StreamingReply:
    model = "reply-stream-fixture"
    settings_hash = "unchanged-fixture-settings"

    def __init__(self, plain_text=False):
        self.plain_text = plain_text
        self.first, self.second, self.reviewing = (asyncio.Event() for _ in range(3))
        self.advance, self.finish, self.approve = (asyncio.Event() for _ in range(3))

    async def stream(self, messages, tools):
        if tools == [VERDICT_TOOL]:
            self.reviewing.set()
            await self.approve.wait()
            yield ModelEvent(
                "tool", call("source_review_verdict", {"accepted": True, "feedback": ""})
            )
            return
        if self.plain_text:
            yield ModelEvent("text", "First")
        else:
            yield ModelEvent(
                "tool_delta", {"index": 0, "name": "reply", "arguments": '{"text":"First'}
            )
        self.first.set()
        await self.advance.wait()
        if self.plain_text:
            yield ModelEvent("text", " second")
        else:
            yield ModelEvent(
                "tool_delta", {"index": 0, "name": "reply", "arguments": '{"text":"First second'}
            )
        self.second.set()
        await self.finish.wait()
        if not self.plain_text:
            yield ModelEvent("tool", call("reply", {"text": "First second"}))


async def preview_page(runtime, turn):
    return await runtime.conversations.page("alice", turn["conversation_id"])


def candidate(page):
    return next((m for m in page["messages"] if m["content"].get("replyPreview")), None)


@pytest.mark.parametrize("plain_text", [False, True])
async def test_candidate_streams_before_model_finish_and_review_without_final_messages(
    store, plain_text
):
    model = StreamingReply(plain_text)
    runtime = Runtime(store, model, require_final_tool=True, review_replies=True)
    run = None
    try:
        turn = await claimed_turn(runtime)
        run = asyncio.create_task(runtime.loop.run(turn, "main"))
        await asyncio.wait_for(model.first.wait(), 3)
        first = await preview_page(runtime, turn)
        mid = candidate(first)["id"]
        assert candidate(first)["content"]["replyPreview"] == {
            "text": "First",
            "state": "generating",
            "clipped": False,
        }
        assert candidate(first)["content"]["text"] == ""
        events = await runtime.conversations.events(
            "alice", turn["conversation_id"], summaries=True
        )
        assert not any(e["kind"] in {"message.delta", "message.completed"} for e in events)
        assert [e["payload"]["text"] for e in events if e["kind"] == "reply.preview"] == ["First"]
        with pytest.raises(DomainError, match="MEMORY_SOURCE_NOT_FOUND"):
            await store.call(
                lambda db: source_snapshot(db, "alice", "event:" + str(events[-1]["id"]))
            )
        await asyncio.sleep(0.11)
        model.advance.set()
        await asyncio.wait_for(model.second.wait(), 3)
        second = await preview_page(runtime, turn)
        assert candidate(second)["content"]["replyPreview"]["text"] == "First second"
        assert candidate(second)["content"]["replyPreview"]["state"] == "generating"
        model.finish.set()
        await asyncio.wait_for(model.reviewing.wait(), 3)
        checking = await preview_page(runtime, turn)
        assert candidate(checking)["content"]["replyPreview"]["text"] == "First second"
        assert candidate(checking)["content"]["replyPreview"]["state"] == "checking"
        assert candidate(checking)["status"] == "completed"
        detail = await runtime.conversations.message_detail("alice", turn["conversation_id"], mid)
        legacy = await runtime.conversations.messages("alice", turn["conversation_id"])
        assert detail["content"]["replyPreview"]["state"] == "checking"
        assert any(m["content"].get("replyPreview") for m in legacy["messages"])
        context = await store.call(lambda db: context_history(db, turn["branch_id"]))
        assert all("replyPreview" not in json.loads(m["content_json"]) for m in context)
        assert all(m.get("content") != "First second" for m in model_messages(context))
        source = await store.call(lambda db: source_snapshot(db, "alice", mid))
        assert "replyPreview" not in json.loads(source["content_json"])
        model.approve.set()
        assert await asyncio.wait_for(run, 3) == "First second"
        final = await preview_page(runtime, turn)
        assert candidate(final) is None
        assert [
            m["content"]["text"]
            for m in final["messages"]
            if m["role"] == "assistant" and m["content"].get("text")
        ] == ["First second"]
        replay = await runtime.conversations.events("alice", turn["conversation_id"])
        assert all(e["payload"].get("clear") for e in replay if e["kind"] == "reply.preview")
        assert all(
            "First second" not in e["payload_json"] for e in replay if e["kind"] == "reply.preview"
        )
    finally:
        if run and not run.done():
            run.cancel()
            await asyncio.gather(run, return_exceptions=True)
        await runtime.close()


@pytest.mark.parametrize("action", ["cancel", "recover", "defer", "forget", "stale_lease"])
async def test_candidate_is_removed_or_hidden_on_terminal_and_identity_boundaries(store, action):
    model = StreamingReply()
    runtime = Runtime(store, model, require_final_tool=True)
    run = None
    try:
        turn = await claimed_turn(runtime)
        run = asyncio.create_task(runtime.loop.run(turn, "main"))
        await asyncio.wait_for(model.first.wait(), 3)
        page = await preview_page(runtime, turn)
        mid = candidate(page)["id"]
        if action == "cancel":
            run.cancel()
            await asyncio.gather(run, return_exceptions=True)
        elif action == "recover":
            await runtime.conversations.recover()
        elif action == "defer":
            assert await runtime.journal.defer(turn)
        elif action == "forget":
            source = next(m["id"] for m in page["messages"] if m["role"] == "user")
            await store.call(
                lambda db: db.execute(
                    "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'forgotten',0)",
                    (source,),
                ),
                write=True,
            )
        else:
            await store.call(
                lambda db: db.execute(
                    "UPDATE turns SET lease_epoch=lease_epoch+1 WHERE id=?", (turn["id"],)
                ),
                write=True,
            )
            with pytest.raises(DomainError, match="TURN_INTERRUPTED"):
                await runtime.journal.preview(turn, mid, "late old writer")
        assert candidate(await preview_page(runtime, turn)) is None
        events = await runtime.conversations.events(
            "alice", turn["conversation_id"], summaries=True
        )
        assert all(e["payload"].get("clear") for e in events if e["kind"] == "reply.preview")
    finally:
        if run and not run.done():
            run.cancel()
            await asyncio.gather(run, return_exceptions=True)
        await runtime.close()


async def test_late_old_failure_cannot_clear_the_new_lease_candidate(store):
    runtime = Runtime(store, StreamingReply(), require_final_tool=True)
    try:
        turn = await claimed_turn(runtime)
        old_mid = await runtime.journal.start(turn)
        await runtime.journal.preview(turn, old_mid, "old")
        await store.call(
            lambda db: db.execute(
                "UPDATE turns SET lease_epoch=lease_epoch+1 WHERE id=?", (turn["id"],)
            ),
            write=True,
        )
        fresh = {**turn, "lease_epoch": turn["lease_epoch"] + 1}
        mid = await runtime.journal.start(fresh)
        await runtime.journal.preview(fresh, mid, "new lease")
        await runtime.journal.fail(turn, "interrupted", "TURN_INTERRUPTED")
        page = await preview_page(runtime, fresh)
        assert candidate(page)["id"] == mid
        assert candidate(page)["content"]["replyPreview"]["text"] == "new lease"
        assert (
            next(item["state"] for item in page["turns"] if item["id"] == turn["id"]) == "running"
        )
    finally:
        await runtime.close()


class RejectThenCorrect:
    model = "reply-source-review-fixture"

    def __init__(self):
        self.draft_ready, self.next_ready = asyncio.Event(), asyncio.Event()
        self.advance, self.finish = asyncio.Event(), asyncio.Event()
        self.attempts, self.reviews = 0, 0

    async def stream(self, messages, tools):
        if tools == [VERDICT_TOOL]:
            self.reviews += 1
            yield ModelEvent(
                "tool",
                call(
                    "source_review_verdict",
                    {
                        "accepted": self.reviews > 1,
                        "feedback": "Wrong result" if self.reviews == 1 else "",
                    },
                ),
            )
            return
        self.attempts += 1
        text = "Unverified claim" if self.attempts == 1 else "Corrected reply"
        yield ModelEvent(
            "tool_delta",
            {"index": 0, "name": "reply", "arguments": json.dumps({"text": text})[:-2]},
        )
        if self.attempts == 1:
            self.draft_ready.set()
            await self.advance.wait()
        else:
            self.next_ready.set()
            await self.finish.wait()
        yield ModelEvent("tool", {**call("reply", {"text": text}), "id": f"reply-{self.attempts}"})


async def test_source_rejection_replaces_candidate_and_only_approved_text_is_final(store):
    model = RejectThenCorrect()
    runtime = Runtime(store, model, require_final_tool=True, review_replies=True)
    run = None
    rebuilding, continue_build = asyncio.Event(), asyncio.Event()
    original_build = runtime.loop.context.build
    build_count = 0

    async def held_build(*args, **kwargs):
        nonlocal build_count
        build_count += 1
        if build_count == 2:
            rebuilding.set()
            await continue_build.wait()
        return await original_build(*args, **kwargs)

    runtime.loop.context.build = held_build
    try:
        turn = await claimed_turn(runtime)
        run = asyncio.create_task(runtime.loop.run(turn, "main"))
        await asyncio.wait_for(model.draft_ready.wait(), 3)
        first = candidate(await preview_page(runtime, turn))
        assert first["content"]["replyPreview"]["text"] == "Unverified claim"
        model.advance.set()
        await asyncio.wait_for(rebuilding.wait(), 3)
        assert candidate(await preview_page(runtime, turn)) is None
        continue_build.set()
        await asyncio.wait_for(model.next_ready.wait(), 3)
        page = await preview_page(runtime, turn)
        assert candidate(page)["id"] != first["id"]
        assert candidate(page)["content"]["replyPreview"]["text"] == "Corrected reply"
        assert not next(m for m in page["messages"] if m["id"] == first["id"])["content"].get(
            "replyPreview"
        )
        assert not any(
            e["kind"] == "message.delta"
            for e in await runtime.conversations.events("alice", turn["conversation_id"])
        )
        model.finish.set()
        assert await asyncio.wait_for(run, 3) == "Corrected reply"
        assert model.reviews == 2
        events = await runtime.conversations.events("alice", turn["conversation_id"])
        assert [e["payload"]["text"] for e in events if e["kind"] == "message.delta"] == [
            "Corrected reply"
        ]
    finally:
        if run and not run.done():
            run.cancel()
            await asyncio.gather(run, return_exceptions=True)
        await runtime.close()


async def test_transport_retry_retracts_the_old_candidate_before_showing_a_fresh_one(store):
    class RetryModel:
        model = "reply-retry-fixture"

        def __init__(self):
            self.ready, self.retried, self.fresh = (asyncio.Event() for _ in range(3))
            self.advance, self.resume, self.finish = (asyncio.Event() for _ in range(3))

        async def stream(self, messages, tools):
            yield ModelEvent(
                "tool_delta", {"index": 4, "name": "reply", "arguments": '{"text":"Old candidate'}
            )
            self.ready.set()
            await self.advance.wait()
            yield ModelEvent("telemetry", {"phase": "retry", "attempt": 1})
            self.retried.set()
            await self.resume.wait()
            yield ModelEvent(
                "tool_delta", {"index": 0, "name": "reply", "arguments": '{"text":"Fresh candidate'}
            )
            self.fresh.set()
            await self.finish.wait()
            yield ModelEvent("tool", call("reply", {"text": "Fresh candidate"}))

    model = RetryModel()
    runtime = Runtime(store, model, require_final_tool=True)
    run = None
    try:
        turn = await claimed_turn(runtime)
        run = asyncio.create_task(runtime.loop.run(turn, "main"))
        await asyncio.wait_for(model.ready.wait(), 3)
        assert (
            candidate(await preview_page(runtime, turn))["content"]["replyPreview"]["text"]
            == "Old candidate"
        )
        model.advance.set()
        await asyncio.wait_for(model.retried.wait(), 3)
        assert candidate(await preview_page(runtime, turn)) is None
        model.resume.set()
        await asyncio.wait_for(model.fresh.wait(), 3)
        assert (
            candidate(await preview_page(runtime, turn))["content"]["replyPreview"]["text"]
            == "Fresh candidate"
        )
        model.finish.set()
        assert await asyncio.wait_for(run, 3) == "Fresh candidate"
        events = await runtime.conversations.events("alice", turn["conversation_id"])
        assert [
            event["payload"]["text"] for event in events if event["kind"] == "message.delta"
        ] == ["Fresh candidate"]
    finally:
        if run and not run.done():
            run.cancel()
            await asyncio.gather(run, return_exceptions=True)
        await runtime.close()
