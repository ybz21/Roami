"""New intents preempt model waits, preserve earlier work and stop at safe boundaries."""

import asyncio
import json

import pytest
from test_runtime import ConversationModel, until

from roami_agent.app import Runtime
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.database import row


async def completed(store, turn_id):
    await until(
        store,
        lambda db: row(db, "SELECT id FROM turns WHERE id=? AND state='completed'", (turn_id,)),
    )


@pytest.mark.parametrize(
    "first_action,second_action",
    [("message", "message"), ("message", "stop"), ("stop", "message"), ("stop", "stop")],
)
async def test_repeated_interruptions_finish_cleanup_and_answer_followups(
    store, monkeypatch, first_action, second_action
):
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class SlowFirst:
        model = "interrupt-cleanup"

        async def stream(self, messages, tools):
            if messages[-1]["content"] == "original":
                entered.set()
                await asyncio.Event().wait()
            yield ModelEvent("text", "Answered")

    runtime = Runtime(store, SlowFirst())
    defer, fail = runtime.journal.defer, runtime.journal.fail

    async def defer_after_cleanup(turn, **kwargs):
        if not kwargs.get("only_if_pending"):
            cleaning.set()
            await release.wait()
        return await defer(turn, **kwargs)

    async def fail_after_cleanup(*args, **kwargs):
        cleaning.set()
        await release.wait()
        return await fail(*args, **kwargs)

    monkeypatch.setattr(runtime.journal, "defer", defer_after_cleanup)
    monkeypatch.setattr(runtime.journal, "fail", fail_after_cleanup)
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        cid = conversation["id"]
        original = await runtime.chat.submit("alice", cid, "original", "original")
        await asyncio.wait_for(entered.wait(), 2)
        followups = []
        for index, action in enumerate((first_action, second_action)):
            if action == "stop":
                await runtime.chat.interrupt("alice", cid, f"stop-{index}")
            else:
                followups.append(await runtime.chat.submit("alice", cid, f"next-{index}", "next"))
            await asyncio.wait_for(cleaning.wait(), 2)
        release.set()
        followups.append(await runtime.chat.submit("alice", cid, "continue", "continue"))
        for receipt in followups:
            await completed(store, receipt["turnId"])
        messages = (await runtime.conversations.messages("alice", cid))["messages"]
        for receipt in followups:
            assert any(
                message["turn_id"] == receipt["turnId"]
                and message["role"] == "assistant"
                and message["content"].get("text") == "Answered"
                for message in messages
            )
        if "stop" not in (first_action, second_action):
            await completed(store, original["turnId"])
        else:
            saved = await store.call(
                lambda db: row(db, "SELECT state FROM turns WHERE id=?", (original["turnId"],))
            )
            assert saved["state"] == "interrupted"
        assert not await store.call(
            lambda db: row(
                db,
                "SELECT id FROM turns WHERE branch_id=? AND state='running'",
                (conversation["active_branch_id"],),
            )
        )
    finally:
        release.set()
        await runtime.close()


async def test_new_question_answers_before_slow_original_and_original_resumes(store):
    entered, blocked = asyncio.Event(), asyncio.Event()
    original_calls = 0

    class Questions:
        model = "intent-scheduling"

        async def stream(self, messages, tools):
            nonlocal original_calls
            resumed = "Resume this original request" in str(messages[-1]["content"])
            if resumed:
                assert "北京天气" in messages[-1]["content"]
                assert "上海" not in str(messages)
                yield ModelEvent("text", "北京：已恢复回答")
            elif messages[-1]["content"] == "北京天气":
                original_calls += 1
                entered.set()
                await blocked.wait()
            else:
                assert not any(m["role"] == "user" and m["content"] == "北京天气" for m in messages)
                assert any(
                    m["role"] == "assistant" and "independent request" in m["content"]
                    for m in messages
                )
                yield ModelEvent("text", "上海：快速回答")

    runtime = Runtime(store, Questions())
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        first = await runtime.chat.submit("alice", conversation["id"], "beijing", "北京天气")
        await asyncio.wait_for(entered.wait(), 2)
        second = await runtime.chat.submit("alice", conversation["id"], "shanghai", "上海天气")
        await completed(store, second["turnId"])
        await completed(store, first["turnId"])
        assert not blocked.is_set() and original_calls == 1
        messages = (await runtime.conversations.messages("alice", conversation["id"]))["messages"]
        answers = [
            m["content"]["text"]
            for m in messages
            if m["role"] == "assistant" and m["status"] == "completed"
        ]
        assert answers == ["上海：快速回答", "北京：已恢复回答"]
        trace = await runtime.traces.get("alice", turn_id=first["turnId"])
        assert len([s for s in trace["spans"] if s["name"] == "model.request"]) == 2
        assert any(s["state"] == "interrupted" for s in trace["spans"])
        waits = [s for s in trace["spans"] if s["name"] == "turn.rescheduled"]
        assert len(waits) == 1 and waits[0]["state"] == "resumed" and waits[0]["durationMs"] >= 0
    finally:
        await runtime.close()


async def test_busy_tools_finish_once_then_new_question_runs_before_continuation(store):
    started, release = asyncio.Event(), asyncio.Event()
    effects = []

    class ToolModel:
        model = "write-boundary"

        async def stream(self, messages, tools):
            if messages[-1]["content"] == "write once":
                yield ModelEvent(
                    "tool", {"id": "write", "function": {"name": "write_probe", "arguments": "{}"}}
                )
            elif messages[-1]["content"] == "quick question":
                yield ModelEvent("text", "Quick answer")
            else:
                assert "persisted write" in str(messages)
                assert "quick question" not in str(messages)
                yield ModelEvent("text", "Write result delivered")

    from roami_agent.protocol.tools import Tool, object_schema

    async def write(args, binding):
        effects.append("write")
        started.set()
        await release.wait()
        return {"summary": "persisted write"}

    runtime = Runtime(store, ToolModel())
    runtime.tools.add(
        Tool(
            "write_probe",
            "Test write boundary",
            object_schema({}),
            write,
            effect="write",
            main=True,
        )
    )
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        first = await runtime.chat.submit("alice", c["id"], "write", "write once")
        await asyncio.wait_for(started.wait(), 2)
        second = await runtime.chat.submit("alice", c["id"], "quick", "quick question")
        await asyncio.sleep(0)
        assert effects == ["write"]
        release.set()
        await completed(store, second["turnId"])
        await completed(store, first["turnId"])
        assert effects == ["write"]
    finally:
        release.set()
        await runtime.close()


async def test_two_background_questions_do_not_need_an_extra_main_model_round(store):
    release = asyncio.Event()

    class Main:
        model = "fast-dispatch"

        async def stream(self, messages, tools):
            if messages[-1]["role"] == "tool":
                raise AssertionError("Do not spend a model request acknowledging accepted work")
            if any(str(m["content"]).startswith("Background task result") for m in messages):
                yield ModelEvent("text", "Result: " + str(messages[-1]["content"]))
            else:
                goal = messages[-1]["content"]
                yield ModelEvent(
                    "tool",
                    {
                        "id": goal,
                        "function": {
                            "name": "delegate",
                            "arguments": json.dumps({"goal": goal, "requestComplete": True}),
                        },
                    },
                )

    class Worker:
        model = "background"

        async def stream(self, messages, tools):
            await release.wait()
            yield ModelEvent("text", "Worker completed " + messages[-1]["content"])

    runtime = Runtime(store, Main(), worker_model=Worker())
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        first = await runtime.chat.submit("alice", c["id"], "beijing", "北京天气")
        await completed(store, first["turnId"])
        second = await runtime.chat.submit("alice", c["id"], "shanghai", "上海天气")
        await completed(store, second["turnId"])
        tasks = await runtime.tasks.list("alice", c["id"])
        assert len(tasks) == 2 and not release.is_set()
        assert {json.loads(t["intent_json"])["goal"] for t in tasks} == {"北京天气", "上海天气"}
        release.set()
        await until(
            store,
            lambda db: (
                db.execute(
                    "SELECT COUNT(*) FROM turns WHERE trigger_kind='completion' AND state='completed'"
                ).fetchone()[0]
                == 2
            ),
        )
        assert all(t["state"] == "succeeded" for t in await runtime.tasks.list("alice", c["id"]))
    finally:
        release.set()
        await runtime.close()


async def test_stop_cancels_a_queued_reply_without_starting_it_or_other_work(store):
    runtime = Runtime(store, ConversationModel())
    try:
        c = await runtime.conversations.create("alice")
        first = await runtime.chat.submit("alice", c["id"], "one", "queued question")
        receipt = await runtime.chat.interrupt("alice", c["id"], "stop")
        assert receipt["turnId"] == first["turnId"]
        await runtime.start()
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='interrupted'", (first["turnId"],)
            ),
        )
        assert (await runtime.chat.interrupt("alice", c["id"], "stop")) == receipt
        assert (
            await store.call(
                lambda db: db.execute("SELECT COUNT(*) FROM prompt_manifests").fetchone()[0]
            )
            == 0
        )
    finally:
        await runtime.close()


async def test_partial_handoff_keeps_working_until_all_requested_parts_are_dispatched(store):
    class Main:
        model = "compound-request"

        async def stream(self, messages, tools):
            goals = [
                json.loads(m["content"]).get("taskId") for m in messages if m["role"] == "tool"
            ]
            index = len(goals)
            assert index < 2, "The final receipt must not cost another model call"
            yield ModelEvent(
                "tool",
                {
                    "id": f"part-{index}",
                    "function": {
                        "name": "delegate",
                        "arguments": json.dumps(
                            {"goal": f"Part {index}", "requestComplete": index == 1}
                        ),
                    },
                },
            )

    from roami_agent.server.configuration import Settings

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", conversation["id"], "both", "Do both parts")
        await completed(store, receipt["turnId"])
        tasks = await runtime.tasks.list("alice", conversation["id"])
        assert {json.loads(t["intent_json"])["goal"] for t in tasks} == {"Part 0", "Part 1"}
        assert {t["origin_message_id"] for t in tasks} == {receipt["messageId"]}
    finally:
        await runtime.close()
