import json

import pytest
from test_runtime import until

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.replies.source_review import (
    REVIEW_INSTRUCTIONS,
    DraftReviewRejected,
    SourceReplyReview,
    reply_text,
    review_message,
)
from roami_agent.storage.database import row


class ReviewModel:
    model = "saved-route"
    settings_hash = "same-parameters"

    def __init__(self, outputs):
        self.outputs, self.requests = iter(outputs), []

    async def stream(self, messages, tools):
        assert tools == []
        self.requests.append(messages)
        value = next(self.outputs)
        if callable(value):
            value = await value()
        yield ModelEvent("telemetry", {"gatewayCallId": "known-call"})
        yield ModelEvent("usage", {"input_tokens": 17, "output_tokens": 3})
        if isinstance(value, BaseException):
            raise value
        yield ModelEvent("text", json.dumps(value))


async def active_review(store, model, text="人数改成7，只回复整数"):
    runtime = Runtime(store, model)
    conversation = await runtime.conversations.create("alice")
    receipt = await runtime.chat.submit("alice", conversation["id"], "request", text)
    await store.call(
        lambda db: db.execute(
            "UPDATE turns SET state='running',lease_epoch=1 WHERE id=?", (receipt["turnId"],)
        ),
        write=True,
    )
    turn = await store.call(
        lambda db: row(
            db,
            "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?",
            (receipt["turnId"],),
        )
    )
    review = SourceReplyReview(store, lambda: model)
    review.timeout = lambda: 0
    review.observe_context(turn, [{"role": "user", "content": text}])
    binding = {
        "owner": "alice",
        "conversation": conversation["id"],
        "turnId": turn["id"],
        "leaseEpoch": 1,
        "toolCallId": "reply-call",
    }
    return runtime, review, turn, binding


@pytest.mark.parametrize(
    "arguments", [{}, {"text": "x", "json": 1}, {"json": float("nan")}, {"text": ""}, {"text": 1}]
)
def test_invalid_reply_transport_cannot_publish(arguments):
    with pytest.raises(DomainError, match="INVALID_TOOL_ARGUMENTS"):
        reply_text(arguments)


def test_json_preserves_types_and_literal_strings():
    value = {"姓名": "周一_名单", "count": 7, "confirmed": False, "notes": None}
    assert json.loads(reply_text({"json": value})) == value


async def test_rejection_requires_correction_and_cache_is_scoped_to_turn(store):
    model = ReviewModel(
        [{"accepted": False, "feedback": "人数已改成7"}, {"accepted": True, "feedback": ""}]
    )
    runtime, review, turn, binding = await active_review(store, model)
    try:
        with pytest.raises(DraftReviewRejected) as error:
            await review.check_reply({"text": "6"}, binding)
        assert error.value.feedback == "人数已改成7"
        await review.check_reply({"text": "7"}, binding)
        await review.check_reply({"text": "7"}, binding)
        assert len(model.requests) == 2
        payload = json.loads(model.requests[0][-1]["content"])
        assert payload["proposedReplyText"] == "6"
        assert payload["userRequests"] == ["人数改成7，只回复整数"]
        review.forget_turn(turn)
        assert not review.contexts and not review.verdicts
    finally:
        await runtime.close()


async def test_preview_and_worker_do_not_start_review(store):
    model = ReviewModel([])
    runtime, review, _, binding = await active_review(store, model)
    try:
        await review.check_reply({"text": "partial"}, {**binding, "toolCallId": None})
        await review.check_reply({"text": "worker"}, {**binding, "runId": "worker-run"})
        await review.check_question({}, {**binding, "runId": "worker-run"})
        assert not model.requests
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "changed", [{"owner": "other"}, {"conversation": "other"}, {"leaseEpoch": 0}]
)
async def test_other_owner_conversation_or_old_lease_cannot_read_source(store, changed):
    model = ReviewModel([])
    runtime, review, _, binding = await active_review(store, model)
    try:
        with pytest.raises(DomainError):
            await review.check_reply({"text": "7"}, {**binding, **changed})
        assert not model.requests
    finally:
        await runtime.close()


async def test_real_ambiguity_allowed_without_fabricated_literal(store):
    model = ReviewModel(
        [
            [{"field": "项目", "value": "枫林", "quote": "项目枫林"}],
            {"accepted": True, "feedback": "同名项目需要选择"},
        ]
    )
    runtime, review, _, binding = await active_review(store, model, "请在项目里新建任务")
    try:
        await review.check_question({"question": "选择哪个项目？"}, binding)
        payload = json.loads(model.requests[-1][-1]["content"])
        assert payload["literalFieldCandidates"] == []
    finally:
        await runtime.close()


async def test_changed_lease_during_model_wait_cannot_publish(store):
    async def change():
        await store.call(lambda db: db.execute("UPDATE turns SET lease_epoch=2"), write=True)
        return {"accepted": True, "feedback": ""}

    model = ReviewModel([change])
    runtime, review, _, binding = await active_review(store, model)
    try:
        with pytest.raises(DomainError, match="TURN_INTERRUPTED"):
            await review.check_reply({"text": "7"}, binding)
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "result",
    [
        {"accepted": "yes", "feedback": ""},
        {"accepted": True},
        DomainError("MODEL_QUOTA_EXCEEDED", 429),
    ],
)
async def test_invalid_or_quota_failed_review_cannot_accept_and_retains_usage(store, result):
    model = ReviewModel([result])
    runtime, review, _, binding = await active_review(store, model)
    try:
        with pytest.raises(DomainError):
            await review.check_reply({"text": "7"}, binding)
        assert not review.verdicts
        records = await runtime.conversations.events("alice", binding["conversation"])
        receipt = next(e["payload"] for e in records if e["kind"] == "reply.source_review")
        assert receipt["usage"] == {"input_tokens": 17, "output_tokens": 3}
        assert receipt["gatewayCallIds"] == ["known-call"]
    finally:
        await runtime.close()


def test_real_image_input_is_forwarded_without_mutating_source():
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,eA=="}}
    payload = {"currentMainContext": [{"role": "user", "content": [image, image]}]}
    message = review_message(payload)
    assert message["content"][1:] == [image]
    assert payload["currentMainContext"][0]["content"] == [image, image]
    assert "data:image" not in message["content"][0]["text"]


async def test_streamed_final_rejection_requires_main_correction(store):
    class Model:
        model = "saved-main"
        reviews = 0
        primary = 0

        async def stream(self, messages, tools):
            if messages[0]["content"] == REVIEW_INSTRUCTIONS:
                self.reviews += 1
                payload = json.loads(messages[-1]["content"])
                accepted = payload["proposedReplyText"] == "7"
                yield ModelEvent(
                    "text", json.dumps({"accepted": accepted, "feedback": "人数改成7"})
                )
            else:
                self.primary += 1
                yield ModelEvent("text", "6" if self.primary == 1 else "7")
            yield ModelEvent("usage", {"input_tokens": 10, "output_tokens": 2})

    model = Model()
    runtime = Runtime(store, model, review_replies=True)
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "one", "人数改成7，只回复整数")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
        )
        snapshot = await runtime.conversations.messages("alice", c["id"])
        committed = [
            m
            for m in snapshot["messages"]
            if m["role"] == "assistant" and m["status"] == "completed" and m["content"].get("text")
        ]
        assert [m["content"]["text"] for m in committed] == ["7"]
        assert model.primary == 2 and model.reviews == 2
        assert not runtime.reply_review.contexts
    finally:
        await runtime.close()


async def test_future_turn_is_not_disclosed_and_forgotten_source_is_blocked(store):
    model = ReviewModel([{"accepted": True, "feedback": ""}])
    runtime, review, _, binding = await active_review(store, model)
    try:
        await runtime.chat.submit("alice", binding["conversation"], "future", "future secret")
        await review.check_reply({"text": "7"}, binding)
        assert "future secret" not in json.dumps(model.requests)
        await store.call(
            lambda db: db.execute(
                "INSERT INTO context_omissions(owner_id,message_id,created_ms,reason) "
                "SELECT 'alice',id,1,'user' FROM messages WHERE turn_id=? AND role='user'",
                (binding["turnId"],),
            ),
            write=True,
        )
        with pytest.raises(DomainError, match="CONTEXT_SOURCE_FORGOTTEN"):
            await review.check_reply({"text": "7"}, binding)
        assert len(model.requests) == 1
    finally:
        await runtime.close()


async def test_latest_tool_observations_invalidate_prior_verdict(store):
    model = ReviewModel(
        [
            {"accepted": True, "feedback": ""},
            {"accepted": False, "feedback": "目标查找结果仍有同名项"},
        ]
    )
    runtime, review, turn, binding = await active_review(store, model)
    try:
        await review.check_reply({"text": "7"}, binding)
        review.observe_context(turn, [{"role": "tool", "content": "two matching targets"}])
        with pytest.raises(DraftReviewRejected):
            await review.check_reply({"text": "7"}, binding)
        payload = json.loads(model.requests[-1][-1]["content"])
        assert payload["currentMainContext"][-1]["content"] == "two matching targets"
    finally:
        await runtime.close()


async def test_cancellation_retains_known_usage_and_releases_preemption_marker(store):
    import asyncio

    model = ReviewModel([asyncio.CancelledError()])
    runtime, review, _, binding = await active_review(store, model)
    markers = []
    review.preemptible = lambda tid, active: markers.append(active)
    try:
        with pytest.raises(asyncio.CancelledError):
            await review.check_reply({"text": "7"}, binding)
        records = await runtime.conversations.events("alice", binding["conversation"])
        receipt = next(e["payload"] for e in records if e["kind"] == "reply.source_review")
        assert receipt["state"] == "interrupted"
        assert receipt["usage"]["input_tokens"] == 17
        assert markers == [True, False]
    finally:
        await runtime.close()


@pytest.mark.parametrize("label", [None, "", "0", "1", "2", "3"])
async def test_container_requires_actual_review_support_before_model_execution(monkeypatch, label):
    from roami_agent.improvement.evaluation.execution import containers
    from roami_agent.server.configuration import Settings

    async def docker(*args, **kwargs):
        assert args[:2] == ("image", "inspect")
        labels = {"org.roami.rsi.shared-daily-policy": "6", "org.roami.rsi.role-instructions": "1"}
        if label is not None:
            labels["org.roami.rsi.source-reply-review"] = label
        return json.dumps([{"Id": "pinned-image", "Config": {"Labels": labels}}]).encode()

    monkeypatch.setattr(containers, "docker_command", docker)
    executor = containers.ContainerExecutor(Settings())
    if label == "3":
        assert (await executor.preflight())["image_id"] == "pinned-image"
    else:
        with pytest.raises(DomainError, match="RSI_CONTAINER_IMAGE_REQUIRED"):
            await executor.preflight()
        assert executor.image_id is None


async def test_structured_draft_uses_separate_source_reading_without_rewriting(store):
    model = ReviewModel([{"name": "源值"}, {"accepted": False, "feedback": "保留字段原文"}])
    runtime, review, _, binding = await active_review(
        store, model, "name源值，其他材料含别值。只返回JSON。"
    )
    try:
        with pytest.raises(DraftReviewRejected):
            await review.check_reply({"json": {"name": "别值"}}, binding)
        assert model.requests[0] == [
            {"role": "user", "content": "name源值，其他材料含别值。只返回JSON。"}
        ]
        payload = json.loads(model.requests[1][-1]["content"])
        assert json.loads(payload["sourceOnlyReading"]) == {"name": "源值"}
        assert json.loads(payload["proposedReplyText"]) == {"name": "别值"}
        assert len(model.requests) == 2
    finally:
        await runtime.close()


async def test_review_sources_reuse_main_projection_instead_of_expanding_compacted_history(store):
    model = ReviewModel([{"accepted": True, "feedback": ""}])
    runtime, review, turn, binding = await active_review(store, model)
    try:
        review.observe_context(
            turn, [{"role": "system", "content": "compacted history"}], source_ids=[]
        )
        await review.check_reply({"text": "7"}, binding)
        payload = json.loads(model.requests[-1][-1]["content"])
        assert payload["userRequests"] == []
        assert payload["currentMainContext"] == [{"role": "system", "content": "compacted history"}]
    finally:
        await runtime.close()


async def test_current_source_survives_filtering_older_assistant_history(store):
    class Model:
        model = "saved-main"

        def __init__(self):
            self.readings = []

        async def stream(self, messages, tools):
            if messages[0]["role"] == "user":
                self.readings.append([m["content"] for m in messages])
                value = messages[-1]["content"]
                yield ModelEvent("text", json.dumps({"name": value}))
            elif messages[0]["content"] == REVIEW_INSTRUCTIONS:
                payload = json.loads(messages[-1]["content"])
                assert payload["userRequests"] == self.readings[-1]
                assert json.loads(payload["sourceOnlyReading"]) == json.loads(
                    payload["proposedReplyText"]
                )
                yield ModelEvent("text", '{"accepted":true,"feedback":""}')
            else:
                value = next(m["content"] for m in reversed(messages) if m["role"] == "user")
                yield ModelEvent(
                    "tool",
                    {
                        "id": "reply-source-check",
                        "type": "function",
                        "function": {
                            "name": "reply",
                            "arguments": json.dumps({"json": {"name": value}}),
                        },
                    },
                )
            yield ModelEvent("usage", {"input_tokens": 10, "output_tokens": 2})

    model = Model()
    runtime = Runtime(store, model, review_replies=True)
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        for index, text in enumerate(["first", "second", "third", "fourth"]):
            receipt = await runtime.chat.submit("alice", c["id"], str(index), text)
            await until(
                store,
                lambda db, receipt=receipt: row(
                    db,
                    "SELECT id FROM turns WHERE id=? AND state='completed'",
                    (receipt["turnId"],),
                ),
            )
        assert model.readings == [
            ["first"],
            ["first", "second"],
            ["first", "second", "third"],
            ["first", "second", "third", "fourth"],
        ]
    finally:
        await runtime.close()


async def test_review_service_invalid_protocol_stops_main_argument_repair(store):
    class Model:
        model = "saved-main"
        primary = 0

        async def stream(self, messages, tools):
            if messages[0]["content"] == REVIEW_INSTRUCTIONS:
                yield ModelEvent("text", "invalid review protocol")
            else:
                self.primary += 1
                if self.primary > 1:
                    raise DomainError("UNEXPECTED_MAIN_RETRY")
                yield ModelEvent(
                    "tool",
                    {
                        "id": "review-failure-control",
                        "type": "function",
                        "function": {"name": "reply", "arguments": '{"text":"7"}'},
                    },
                )
            yield ModelEvent("usage", {"input_tokens": 10, "output_tokens": 2})

    model = Model()
    runtime = Runtime(store, model, review_replies=True)
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "one", "人数为7，只回复整数")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='failed'", (receipt["turnId"],)
            ),
        )
        assert model.primary == 1
        records = await runtime.conversations.events("alice", c["id"])
        assert any(
            e["kind"] == "reply.source_review" and e["payload"]["error"] == "MODEL_OUTPUT_INVALID"
            for e in records
        )
    finally:
        await runtime.close()


async def test_review_model_timeout_retains_its_own_deadline_code(store):
    import asyncio

    class SlowReview:
        model = "saved-main"

        async def stream(self, messages, tools):
            await asyncio.Event().wait()
            yield ModelEvent("text", "unreachable")

    model = SlowReview()
    runtime, review, _, binding = await active_review(store, model)
    review.timeout = lambda: 0.001
    try:
        with pytest.raises(DomainError, match="MODEL_DEADLINE"):
            await review.check_reply({"text": "7"}, binding)
    finally:
        await runtime.close()


async def test_new_user_can_preempt_review_and_original_resumes_without_losing_usage(store):
    import asyncio

    entered, release = asyncio.Event(), asyncio.Event()

    class Model:
        model = "saved-main"

        def __init__(self):
            self.calls = 0
            self.original_reviews = 0

        async def stream(self, messages, tools):
            if messages[0]["content"] == REVIEW_INSTRUCTIONS:
                payload = json.loads(messages[-1]["content"])
                if payload["proposedReplyText"] == "original":
                    self.original_reviews += 1
                    yield ModelEvent("usage", {"input_tokens": 17, "output_tokens": 3})
                    if self.original_reviews == 1:
                        entered.set()
                        await asyncio.Event().wait()
                    await release.wait()
                yield ModelEvent("text", '{"accepted":true,"feedback":""}')
            else:
                self.calls += 1
                value = next(m["content"] for m in reversed(messages) if m["role"] == "user")
                if "original" in value:
                    value = "original"
                yield ModelEvent(
                    "tool",
                    {
                        "id": "review-control-" + str(self.calls),
                        "type": "function",
                        "function": {"name": "reply", "arguments": json.dumps({"text": value})},
                    },
                )
            yield ModelEvent("usage", {"input_tokens": 10, "output_tokens": 2})

    model = Model()
    runtime = Runtime(store, model, review_replies=True)
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        first = await runtime.chat.submit("alice", c["id"], "first", "original")
        await asyncio.wait_for(entered.wait(), 2)
        second = await runtime.chat.submit("alice", c["id"], "second", "next")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (second["turnId"],)
            ),
        )
        release.set()
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (first["turnId"],)
            ),
        )
        events = await runtime.conversations.events("alice", c["id"])
        interrupted = [
            e["payload"]
            for e in events
            if e["kind"] == "reply.source_review" and e["payload"]["state"] == "interrupted"
        ]
        assert len(interrupted) == 1
        assert interrupted[0]["usage"] == {"input_tokens": 17, "output_tokens": 3}
        assert model.original_reviews == 2
        assert not runtime.reply_review.contexts
    finally:
        release.set()
        await runtime.close()


@pytest.mark.parametrize("wrong", ["paraphrase", None, True])
async def test_reviewer_cannot_accept_a_grounded_reading_contradiction(store, wrong):
    model = ReviewModel([{"label": "Play together"}, {"accepted": True, "feedback": ""}])
    runtime, review, _, binding = await active_review(
        store, model, "labelPlay together，只返回JSON。"
    )
    draft = {"json": {"label": wrong}}
    try:
        with pytest.raises(DraftReviewRejected):
            await review.check_reply(draft, binding)
        assert draft == {"json": {"label": wrong}}
        assert model.requests == [[{"role": "user", "content": "labelPlay together，只返回JSON。"}]]
    finally:
        await runtime.close()


async def test_forgotten_source_cannot_return_reading_feedback_after_model_wait(store):
    async def forget():
        await store.call(
            lambda db: db.execute(
                "INSERT INTO context_omissions(owner_id,message_id,created_ms,reason) "
                "SELECT 'alice',id,1,'user' FROM messages WHERE role='user'"
            ),
            write=True,
        )
        return {"label": "Play together"}

    model = ReviewModel([forget])
    runtime, review, _, binding = await active_review(
        store, model, "labelPlay together，只返回JSON。"
    )
    try:
        with pytest.raises(DomainError, match="CONTEXT_SOURCE_FORGOTTEN"):
            await review.check_reply({"json": {"label": "wrong"}}, binding)
    finally:
        await runtime.close()


async def test_proven_field_survives_a_later_inconsistent_reading_and_context_rebuild(store):
    model = ReviewModel(
        [
            {"label": "Play together"},
            {"labelPlay together": True},
            {"labelPlay together": True},
            {"accepted": True, "feedback": ""},
        ]
    )
    runtime, review, turn, binding = await active_review(
        store, model, "labelPlay together，只返回JSON。"
    )
    try:
        with pytest.raises(DraftReviewRejected):
            await review.check_reply({"json": {"label": "paraphrase"}}, binding)
        review.observe_context(
            turn,
            [
                {"role": "user", "content": "labelPlay together，只返回JSON。"},
                {"role": "assistant", "content": "retry"},
            ],
        )
        with pytest.raises(DraftReviewRejected) as error:
            await review.check_reply({"json": {"label": "labelPlay together"}}, binding)
        assert "field name" in error.value.feedback
        await review.check_reply({"json": {"label": "Play together"}}, binding)
        assert len(model.requests) == 4
        review.forget_turn(turn)
        assert not review.contexts and not review.verdicts
    finally:
        await runtime.close()


async def test_background_completion_is_not_reviewed_as_the_latest_user_request(store):
    model = ReviewModel([])
    runtime, review, turn, _binding = await active_review(
        store, model, "只讨论预算，不要生成报告。"
    )
    try:
        await store.call(
            lambda db: db.execute(
                "UPDATE turns SET trigger_kind='completion' WHERE id=?", (turn["id"],)
            ),
            write=True,
        )
        completion = {**turn, "trigger_kind": "completion"}
        review.observe_context(
            completion, [{"role": "system", "content": "Earlier report delivered"}]
        )
        assert await review.final_error(completion, "Earlier report is delivered.") is None
        assert not model.requests
    finally:
        await runtime.close()


@pytest.mark.parametrize("kind", ["answer", "question"])
@pytest.mark.parametrize(
    "change,code",
    [
        ("forgotten", "CONTEXT_SOURCE_FORGOTTEN"),
        ("lease", "TURN_INTERRUPTED"),
        ("context", "REPLY_REVIEW_SOURCE_CHANGED"),
        ("model", "REPLY_REVIEW_SOURCE_CHANGED"),
        ("settings", "REPLY_REVIEW_SOURCE_CHANGED"),
    ],
)
async def test_source_change_after_reading_cannot_start_another_model_request(
    store, kind, change, code
):
    async def changed_source():
        if change == "forgotten":
            await store.call(
                lambda db: db.execute(
                    "INSERT INTO context_omissions(owner_id,message_id,created_ms,reason) SELECT 'alice',id,1,'user' FROM messages WHERE role='user'"
                ),
                write=True,
            )
        elif change == "lease":
            await store.call(
                lambda db: db.execute(
                    "UPDATE turns SET lease_epoch=lease_epoch+1 WHERE id=?", (turn["id"],)
                ),
                write=True,
            )
        elif change == "context":
            review.observe_context(turn, [{"role": "user", "content": "rebuilt context"}])
        elif change == "settings":
            model.settings_hash = "changed-parameters"
        else:
            replacement = ReviewModel([])
            review.model = lambda: replacement
        return {"count": 7} if kind == "answer" else []

    model = ReviewModel([changed_source, {"accepted": True, "feedback": ""}])
    runtime, review, turn, binding = await active_review(store, model, "人数7，只返回JSON。")
    try:
        with pytest.raises(DomainError, match=code):
            if kind == "answer":
                await review.check_reply({"json": {"count": 7}}, binding)
            else:
                await review.check_question({"prompt": "Choose the remaining destination"}, binding)
        assert len(model.requests) == 1
    finally:
        await runtime.close()
