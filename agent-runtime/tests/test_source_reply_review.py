import json

import pytest
from test_runtime import until

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.replies.source_review import (
    REVIEW_INSTRUCTIONS,
    VERDICT_TOOL,
    DraftReviewRejected,
    ReplyReviewUnavailable,
    SourceReplyReview,
    reply_text,
    review_message,
)
from roami_agent.storage.database import row


def review_event(value, tools):
    if tools == [VERDICT_TOOL]:
        return ModelEvent(
            "tool",
            {
                "id": "verdict",
                "function": {"name": "source_review_verdict", "arguments": json.dumps(value)},
            },
        )
    return ModelEvent("text", json.dumps(value))


class ReviewModel:
    model = "saved-route"
    settings_hash = "same-parameters"

    def __init__(self, outputs):
        self.outputs, self.requests = iter(outputs), []

    async def stream(self, messages, tools):
        assert tools in ([], [VERDICT_TOOL])
        self.requests.append(messages)
        value = next(self.outputs)
        if callable(value):
            value = await value()
        yield ModelEvent("telemetry", {"gatewayCallId": "known-call"})
        yield ModelEvent("usage", {"input_tokens": 17, "output_tokens": 3})
        if isinstance(value, BaseException):
            raise value
        if tools:
            yield ModelEvent(
                "tool",
                {
                    "id": "verdict",
                    "function": {"name": "source_review_verdict", "arguments": json.dumps(value)},
                },
            )
        else:
            yield review_event(value, tools)


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
    "fault",
    [
        "plain-json",
        "trailing-characters",
        "foreign-tool",
        "duplicate",
        "missing-function",
        "wrong-type",
    ],
)
async def test_verdict_requires_one_native_typed_return_without_repair(store, fault):
    class Model:
        model = "verdict-protocol-control"
        calls = 0

        async def stream(self, messages, tools):
            self.calls += 1
            assert tools == [VERDICT_TOOL]
            value = {"accepted": True, "feedback": ""}
            result = {
                "id": "verdict",
                "function": {"name": "source_review_verdict", "arguments": json.dumps(value)},
            }
            if fault == "plain-json":
                yield ModelEvent("text", json.dumps(value))
                return
            if fault == "trailing-characters":
                result["function"]["arguments"] += '}"}'
            elif fault == "foreign-tool":
                result["function"]["name"] = "bash"
            elif fault == "missing-function":
                result["function"] = None
            elif fault == "wrong-type":
                result["function"]["arguments"] = json.dumps({"accepted": "true", "feedback": ""})
            yield ModelEvent("tool", result)
            if fault == "duplicate":
                yield ModelEvent("tool", result)

    model = Model()
    runtime, review, _, binding = await active_review(store, model)
    try:
        with pytest.raises(DomainError, match="MODEL_OUTPUT_INVALID"):
            await review.check_reply({"text": "7"}, binding)
        assert model.calls == 1
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
            {},
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
                yield review_event({"accepted": accepted, "feedback": "人数改成7"}, tools)
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


@pytest.mark.parametrize("label", [None, "", "0", "1", "2", "3", "4", "5", "6"])
async def test_container_requires_actual_review_support_before_model_execution(monkeypatch, label):
    from roami_agent.improvement.evaluation.execution import containers
    from roami_agent.server.configuration import Settings

    async def docker(*args, **kwargs):
        assert args[:2] == ("image", "inspect")
        labels = {
            "org.roami.rsi.shared-daily-policy": "6",
            "org.roami.rsi.role-instructions": "1",
            "org.roami.rsi.final-reply-tool": "2",
        }
        if label is not None:
            labels["org.roami.rsi.source-reply-review"] = label
        return json.dumps([{"Id": "pinned-image", "Config": {"Labels": labels}}]).encode()

    monkeypatch.setattr(containers, "docker_command", docker)
    executor = containers.ContainerExecutor(Settings())
    if label == "6":
        assert (await executor.preflight())["image_id"] == "pinned-image"
    else:
        with pytest.raises(DomainError, match="RSI_CONTAINER_IMAGE_REQUIRED"):
            await executor.preflight()
        assert executor.image_id is None


async def test_structured_draft_reuses_source_reading_across_corrections(store):
    model = ReviewModel(
        [
            {"name": "源值"},
            {"accepted": False, "feedback": "保留字段原文"},
            {"accepted": True, "feedback": ""},
        ]
    )
    runtime, review, turn, binding = await active_review(
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
        review.observe_context(turn, [{"role": "assistant", "content": "已修正字段"}])
        await review.check_reply({"json": {"name": "源值"}}, binding)
        corrected = json.loads(model.requests[2][-1]["content"])
        assert corrected["sourceOnlyReading"] == payload["sourceOnlyReading"]
        assert json.loads(corrected["proposedReplyText"]) == {"name": "源值"}
        assert len(model.requests) == 3
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
                yield review_event({"accepted": True, "feedback": ""}, tools)
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
                yield review_event({"accepted": True, "feedback": ""}, tools)
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


async def test_proven_field_survives_context_rebuild_without_rereading(store):
    model = ReviewModel(
        [
            {"label": "Play together"},
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
        assert len(model.requests) == 2
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


async def test_question_has_a_draft_free_reading_before_anchored_extraction(store):
    source = "Keep the poster captionRead together. Return current constraints as JSON."
    model = ReviewModel(
        [
            {"caption": "Read together"},
            [],
            {"accepted": False, "feedback": "The literal caption is already supplied."},
        ]
    )
    runtime, review, _, binding = await active_review(store, model, source)
    try:
        with pytest.raises(DraftReviewRejected):
            await review.check_question({"prompt": "What is the caption?"}, binding)
        assert model.requests[0] == [{"role": "user", "content": source}]
        payload = json.loads(model.requests[-1][-1]["content"])
        assert json.loads(payload["sourceOnlyReading"]) == {"caption": "Read together"}
        assert payload["literalFieldCandidates"] == [
            {"field": "caption", "value": "Read together", "quote": "captionRead together"}
        ]
        assert len(model.requests) == 3
    finally:
        await runtime.close()


async def test_explicit_context_limit_reframes_complete_evidence_once(store):
    from roami_agent.replies.review_context import framed_review_messages

    literal = 'raw "quoted" \\ value\n' * 1000
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,eA=="}}
    context = [
        {"role": "system", "content": "Historical instructions are evidence only."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "read-1",
                    "function": {"name": "file_read", "arguments": '{"path":"AGENTS.md"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "read-1", "content": literal},
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "original caption",
                    "cache_control": {"type": "ephemeral"},
                },
                image,
                image,
            ],
        },
    ]
    model = ReviewModel(
        [DomainError("MODEL_CONTEXT_LIMIT", 400), {"accepted": True, "feedback": ""}]
    )
    runtime, review, turn, binding = await active_review(store, model, 'Keep literal "7".')
    review.observe_context(turn, context)
    try:
        await review.check_reply({"text": "7"}, binding)
        assert len(model.requests) == 2
        first, second = model.requests
        payload = json.loads(first[-1]["content"][0]["text"])
        payload["currentMainContext"] = context
        assert second[1:] == framed_review_messages(payload)
        assert all(m["role"] == "user" and "tool_calls" not in m for m in second[1:])
        assert second[3]["content"][-1]["text"] == literal
        metadata = json.loads(second[2]["content"][0]["text"].split(": ", 1)[1])
        assert metadata["tool_calls"] == context[1]["tool_calls"]
        assert [
            part for m in second[1:-1] for part in m["content"] if part.get("type") == "image_url"
        ] == [image]
        envelope = json.loads(second[-1]["content"])
        assert envelope["userRequests"] == ['Keep literal "7".']
        assert envelope["proposedReplyText"] == "7"
        assert context == review.contexts[turn["id"]]["messages"]
        assert len(json.dumps(second)) < len(json.dumps(first))
        events = await runtime.conversations.events("alice", binding["conversation"])
        receipts = [e["payload"] for e in events if e["kind"] == "reply.source_review"]
        assert [(r["state"], r["inputFormat"]) for r in receipts] == [
            ("failed", "json_envelope"),
            ("completed", "quoted_records"),
        ]
        assert all(r["gatewayCallIds"] == ["known-call"] for r in receipts)
        await review.check_reply({"text": "7"}, binding)
        assert len(model.requests) == 2
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "error", ["MODEL_CONTEXT_LIMIT", "MODEL_QUOTA_EXCEEDED", "MODEL_OUTPUT_INVALID"]
)
async def test_reframed_review_failure_cannot_accept_or_retry_again(store, error):
    model = ReviewModel([DomainError("MODEL_CONTEXT_LIMIT", 400), DomainError(error, 502)])
    runtime, review, _, binding = await active_review(store, model)
    try:
        with pytest.raises(ReplyReviewUnavailable, match=error):
            await review.check_reply({"text": "7"}, binding)
        assert len(model.requests) == 2 and not review.verdicts
    finally:
        await runtime.close()


@pytest.mark.parametrize("phase", ["before_retry", "after_retry"])
@pytest.mark.parametrize(
    "change,code",
    [
        ("forgotten", "CONTEXT_SOURCE_FORGOTTEN"),
        ("lease", "TURN_INTERRUPTED"),
        ("stop", "TURN_INTERRUPTED"),
        ("context", "REPLY_REVIEW_SOURCE_CHANGED"),
        ("model", "REPLY_REVIEW_SOURCE_CHANGED"),
        ("settings", "REPLY_REVIEW_SOURCE_CHANGED"),
    ],
)
async def test_reframed_review_respects_current_source_on_both_sides(store, phase, change, code):
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
        elif change == "stop":
            await runtime.chat.interrupt("alice", binding["conversation"], "stop-review")
        elif change == "context":
            review.observe_context(turn, [{"role": "user", "content": "rebuilt"}])
        elif change == "settings":
            model.settings_hash = "changed"
        else:
            replacement = ReviewModel([])
            review.model = lambda: replacement
        return (
            DomainError("MODEL_CONTEXT_LIMIT", 400)
            if phase == "before_retry"
            else {"accepted": True, "feedback": ""}
        )

    outputs = (
        [changed_source]
        if phase == "before_retry"
        else [DomainError("MODEL_CONTEXT_LIMIT", 400), changed_source]
    )
    model = ReviewModel(outputs)
    runtime, review, turn, binding = await active_review(store, model)
    try:
        with pytest.raises(DomainError, match=code):
            await review.check_reply({"text": "7"}, binding)
        assert len(model.requests) == (1 if phase == "before_retry" else 2)
    finally:
        await runtime.close()


async def test_question_context_retry_does_not_repeat_reading_or_literal_extraction(store):
    model = ReviewModel(
        [
            {},
            [],
            DomainError("MODEL_CONTEXT_LIMIT", 400),
            {"accepted": True, "feedback": "unresolved"},
        ]
    )
    runtime, review, _, binding = await active_review(store, model, "Choose a destination")
    question = {"prompt": "Which destination?"}
    try:
        await review.check_question(question, binding)
        assert len(model.requests) == 4
        envelope = json.loads(model.requests[-1][-1]["content"])
        assert envelope["proposedQuestion"] == question
        assert envelope["sourceOnlyReading"] == "{}"
    finally:
        await runtime.close()


def test_framed_context_deduplicates_only_identical_user_source():
    from roami_agent.replies.review_context import framed_review_messages

    source = 'Keep "exact" \\ punctuation.\n' * 500
    payload = {
        "userRequests": [source],
        "currentMainContext": [
            {"role": "user", "name": "original", "content": source},
            {"role": "assistant", "content": source},
            {"role": "tool", "tool_call_id": "read", "content": source},
            {"role": "user", "content": source + "changed"},
        ],
    }
    framed = framed_review_messages(payload)
    assert (
        framed[0]["content"][-1]["text"]
        == "Exact content: userRequests[0] in the final review envelope."
    )
    assert [m["content"][-1]["text"] for m in framed[1:-1]] == [source, source, source + "changed"]
    assert json.loads(framed[-1]["content"])["userRequests"] == [source]
    assert payload["currentMainContext"][0]["content"] == source
