"""Delivery validates mistakes before publishing and preserves explicit raw content."""

import json

import pytest
from test_coordinator_handoff import call
from test_main_intent_scheduling import completed
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.replies.answer_contract import validate_answer
from roami_agent.replies.task_progress import request_language, task_progress
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import rows


@pytest.mark.parametrize("mode", ["detailed", "debug"])
def test_requested_quotes_and_raw_fields_are_not_rewritten_or_truncated(mode):
    text = "stopConfirmed=false; 状态 interrupted；随时告诉我。" * 4000
    source = "完整原样给我原始字段和详细记录"
    assert (
        validate_answer(
            {"mode": mode, "text": text, "language": "zh", "scopeQuote": source}, source
        )
        == text
    )
    with pytest.raises(DomainError, match="REPLY_SCOPE_QUOTE_REQUIRED"):
        validate_answer(
            {"mode": mode, "text": text, "language": "zh", "scopeQuote": "invented request"}, source
        )


def test_actual_user_language_and_explicit_override_are_distinct():
    assert request_language("Where is the report?", "zh") == "en"
    assert request_language("报告在哪？", "en") == "zh"
    assert request_language("Please answer in Chinese.", "zh", "answer in Chinese") == "zh"
    assert (
        task_progress([{"state": "succeeded", "replyLanguage": "en"}], "zh", single=True)
        == "The task is complete."
    )
    assert "尚未确认停止" in task_progress(
        [{"state": "interrupted", "latestAttempt": {"stopConfirmed": False}}], "zh", single=False
    )
    assert task_progress([], "en", single=False) == "No tasks are running."


async def test_specific_task_reply_cannot_silently_fall_back_to_queue_overview(store):
    runtime = Runtime(store, ConversationModel())
    try:
        schema = runtime.tools.registry["task_reply"].schema
        assert "taskId" in schema["required"]
        assert "taskId" not in runtime.tools.registry["task_queue_reply"].schema["properties"]
        with pytest.raises(DomainError, match="INVALID_TOOL_ARGUMENTS"):
            await runtime.tools.invoke(call("task_reply", {}), "main", {})
        assert not await runtime.tasks.list("alice")
    finally:
        await runtime.close()


@pytest.mark.parametrize("plain", [False, True])
async def test_rejected_answer_is_not_published_and_correction_ends_without_rewrite(store, plain):
    rounds = 0

    class Main:
        model = "delivery-contract"

        async def stream(self, messages, tools):
            nonlocal rounds
            rounds += 1
            if rounds == 1:
                if plain:
                    yield ModelEvent("text", "已完成，随时告诉我。")
                    return
                yield ModelEvent(
                    "tool",
                    call(
                        "reply", {"mode": "brief", "text": "已完成，随时告诉我。", "language": "zh"}
                    ),
                )
            else:
                assert rounds == 2
                assert json.loads(messages[-1]["content"])["error"] == "REPLY_BOILERPLATE"
                if plain:
                    assert messages[-2]["tool_calls"][0]["type"] == "function"
                    assert messages[-1]["tool_call_id"].startswith("call_")
                    assert len(messages[-1]["tool_call_id"]) == 29
                yield ModelEvent(
                    "tool",
                    call(
                        "reply",
                        {"mode": "brief", "text": "已完成。", "language": "zh"},
                        "corrected",
                    ),
                )

    runtime = Runtime(store, Main(), settings=Settings(workers=0), memory_model=ConversationModel())
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "answer", "告诉我结果")
        await completed(store, receipt["turnId"])
        transcript = await runtime.conversations.messages("alice", c["id"])
        replies = [
            m["content"]["text"]
            for m in transcript["messages"]
            if m["role"] == "assistant" and m["content"].get("text")
        ]
        assert replies == ["已完成。"]
        assert rounds == 2
        assert await runtime.tasks.list("alice", c["id"]) == []
        receipts = await store.call(
            lambda db: rows(
                db,
                "SELECT state FROM tool_calls WHERE turn_id=? ORDER BY rowid",
                (receipt["turnId"],),
            )
        )
        assert [r["state"] for r in receipts] == ["failed", "succeeded"]
    finally:
        await runtime.close()


@pytest.mark.parametrize("queue", [False, True])
async def test_completion_callback_cannot_replace_findings_with_generic_status(store, queue):
    rounds, task_id = 0, None

    class Main:
        model = "completion-content"

        async def stream(self, messages, tools):
            nonlocal rounds
            rounds += 1
            if rounds == 1:
                yield ModelEvent(
                    "tool",
                    call(
                        "task_queue_reply" if queue else "task_reply",
                        {} if queue else {"taskId": task_id},
                    ),
                )
            else:
                assert rounds == 2
                assert json.loads(messages[-1]["content"])["error"] == (
                    "TASK_REPLY_TASK_MISMATCH" if queue else "TASK_RESULT_REQUIRED"
                )
                yield ModelEvent("tool", call("reply", {"text": "济南18至24摄氏度，无降雨。"}))

    runtime = Runtime(store, Main(), settings=Settings(workers=0), memory_model=ConversationModel())
    try:
        c = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", c["id"], "查看济南天气", key="weather", record_intent=True
        )
        task_id = task["id"]
        attempt = await store.call(
            lambda db: rows(db, "SELECT * FROM task_attempts WHERE task_id=?", (task_id,))[0]
        )
        await runtime.dispatch.complete(
            task,
            attempt,
            {"state": "succeeded", "summary": "受控测试数据：济南18至24摄氏度，无降雨。"},
            "succeeded",
        )
        job = await store.call(
            lambda db: rows(
                db,
                "SELECT * FROM jobs WHERE kind='turn.run' AND json_extract(payload_json,'$.completion.taskId')=?",
                (task_id,),
            )[0]
        )
        turn = await runtime.mailbox.claim(job)
        await runtime.loop.run(
            turn, "main", completion=json.loads(job["payload_json"])["completion"]
        )
        transcript = await runtime.conversations.messages("alice", c["id"])
        assert transcript["messages"][-1]["content"]["text"] == "济南18至24摄氏度，无降雨。"
        assert len(await runtime.tasks.list("alice", c["id"])) == 1
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "state,result",
    [
        ("cancelled", {"state": "cancelled"}),
        ("failed", {"state": "failed", "retryable": False}),
        ("succeeded", {"state": "succeeded", "retryable": False}),
    ],
)
async def test_stopped_callback_cannot_restart_but_success_can_continue_authorized_stages(
    store, state, result
):
    effects, rounds = [], 0

    class Main:
        model = "callback-write-guard"

        async def stream(self, messages, tools):
            nonlocal rounds
            rounds += 1
            if rounds == 1:
                yield ModelEvent("tool", call("mutate", {}))
            else:
                assert rounds == 2
                outcome = json.loads(messages[-1]["content"])
                if state == "succeeded":
                    assert outcome == {"ok": True}
                else:
                    assert outcome["error"] == "TASK_COMPLETION_RESTART_FORBIDDEN"
                yield ModelEvent(
                    "tool",
                    call("reply", {"text": "任务已停止。", "mode": "brief", "language": "zh"}),
                )

    async def mutate(args, binding):
        effects.append(True)
        return {"ok": True}

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    runtime.tools.directory = None
    runtime.tools.add(
        Tool("mutate", "Start work", object_schema({}), mutate, main=True, effect="write")
    )
    try:
        c = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", c["id"], "查询资料", key="old", record_intent=True
        )
        attempt = await store.call(
            lambda db: rows(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))[0]
        )
        await runtime.dispatch.complete(task, attempt, result, state)
        job = await store.call(
            lambda db: rows(
                db,
                "SELECT * FROM jobs WHERE kind='turn.run' AND json_extract(payload_json,'$.completion.taskId')=?",
                (task["id"],),
            )[0]
        )
        turn = await runtime.mailbox.claim(job)
        await runtime.loop.run(
            turn, "main", completion=json.loads(job["payload_json"])["completion"]
        )
        assert effects == ([True] if state == "succeeded" else []) and rounds == 2
        assert len(await runtime.tasks.list("alice", c["id"])) == 1
    finally:
        await runtime.close()


async def test_progress_reads_authoritative_outer_state_in_one_model_call(store):
    calls = 0
    task_id = None

    class Main:
        model = "state-delivery"

        async def stream(self, messages, tools):
            nonlocal calls
            calls += 1
            assert calls == 1
            yield ModelEvent("tool", call("task_reply", {"taskId": task_id, "language": "zh"}))

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    c = await runtime.conversations.create("alice")
    task = await runtime.tasks.create(
        "alice", c["id"], "Earlier work", key="prior", record_intent=True
    )
    task_id = task["id"]
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='interrupted' WHERE id=?", (task_id,)),
        write=True,
    )
    await runtime.start()
    try:
        receipt = await runtime.chat.submit("alice", c["id"], "status", "Is the task complete?")
        await completed(store, receipt["turnId"])
        transcript = await runtime.conversations.messages("alice", c["id"])
        assert (
            transcript["messages"][-1]["content"]["text"]
            == "The task was interrupted; the result is unconfirmed."
        )
        assert len(await runtime.tasks.list("alice", c["id"])) == 1
        assert calls == 1
    finally:
        await runtime.close()


async def test_large_requested_debug_answer_is_delivered_whole_without_externalization(store):
    payload = "state=interrupted; stopConfirmed=false; 完整原文。" * 5000
    question = "请完整原样输出所有调试字段"

    class Main:
        model = "large-debug-answer"

        async def stream(self, messages, tools):
            yield ModelEvent(
                "tool",
                call(
                    "reply",
                    {"text": payload, "mode": "debug", "language": "zh", "scopeQuote": question},
                ),
            )
            yield ModelEvent("usage", {"input_tokens": 1230, "output_tokens": 10})

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "large", question)
        await completed(store, receipt["turnId"])
        transcript = await runtime.conversations.messages("alice", c["id"])
        assert transcript["messages"][-1]["content"]["text"] == payload
        assert not await store.call(lambda db: rows(db, "SELECT id FROM artifacts"))
        assert (
            len(
                await store.call(
                    lambda db: rows(
                        db, "SELECT id FROM prompt_manifests WHERE turn_id=?", (receipt["turnId"],)
                    )
                )
            )
            == 1
        )
        usage = await store.call(
            lambda db: rows(
                db, "SELECT usage_json FROM prompt_manifests WHERE turn_id=?", (receipt["turnId"],)
            )[0]["usage_json"]
        )
        assert json.loads(usage)["input_tokens"] == 1230
    finally:
        await runtime.close()
