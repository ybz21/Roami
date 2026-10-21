"""Task acceptance is a turn-scoped handoff, never permission to poll or restart."""

import json

import pytest
from test_main_intent_scheduling import completed
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import rows


def call(name, args, key=None, *, cli=False):
    if cli:
        args = {"argv": ["roami", "agent", "task", "steer", "--input", json.dumps(args)]}
        name = "bash"
    return {"id": key or name, "function": {"name": name, "arguments": json.dumps(args)}}


@pytest.mark.parametrize(
    "name,cli", [("delegate", False), ("task_steer", False), ("task_steer", True)]
)
async def test_missing_handoff_flag_rejected_before_side_effects(store, name, cli):
    runtime = Runtime(store, ConversationModel())
    args = (
        {"goal": "Requested lookup"}
        if name == "delegate"
        else {
            "taskId": "nonexistent",
            "revision": 1,
            "text": "Requested update",
        }
    )
    try:
        with pytest.raises(DomainError, match="INVALID_TOOL_ARGUMENTS"):
            await runtime.tools.invoke(call(name, args, cli=cli), "main", {})
        assert await runtime.tasks.list("alice") == []
        assert not await store.call(lambda db: rows(db, "SELECT * FROM jobs"))
        if name == "delegate":
            wire = next(t for t in runtime.tools.catalog() if t["function"]["name"] == name)
            assert "requestComplete" in wire["function"]["parameters"]["required"]
        else:
            commands = runtime.tools.directory.command_entries("main")[0]["commands"]
            schema = next(
                c["inputSchema"] for c in commands if c["argv"][1:4] == ["agent", "task", "steer"]
            )
            assert "requestComplete" in schema["required"]
    finally:
        await runtime.close()


async def test_same_turn_cannot_restart_or_fetch_accepted_task_results_but_new_status_can(store):
    phase = 0
    task_id = None

    class Main:
        model = "handoff-guard"

        async def stream(self, messages, tools):
            nonlocal phase, task_id
            phase += 1
            if phase == 1:
                yield ModelEvent(
                    "tool", call("delegate", {"goal": "Lookup", "requestComplete": False})
                )
            elif phase == 2:
                receipt = json.loads(messages[-1]["content"])
                task_id = receipt["taskId"]
                yield ModelEvent("tool", call("task_status", {"taskId": task_id}))
            elif phase == 3:
                receipt = json.loads(messages[-1]["content"])
                assert receipt["error"] == "TASK_ALREADY_HANDED_OFF"
                assert "latestAttempt" not in receipt
                yield ModelEvent(
                    "tool",
                    call(
                        "task_steer",
                        {
                            "taskId": task_id,
                            "revision": 1,
                            "text": "Repeat",
                            "requestComplete": True,
                        },
                    ),
                )
            elif phase == 4:
                rejection = json.loads(messages[-1]["content"])
                assert rejection["error"] == "TASK_ALREADY_HANDED_OFF"
                assert rejection["executionStarted"] is False
                yield ModelEvent("text", "已交给任务，完成后告诉你。")
            elif phase == 5:
                assert messages[-1]["content"] == "刚才的任务完成了吗？"
                yield ModelEvent("tool", call("task_status", {"taskId": task_id}))
            elif phase == 6:
                status = json.loads(messages[-1]["content"])
                assert status[0]["id"] == task_id
                yield ModelEvent("text", "还在排队。")
            else:
                assert phase == 7
                yield ModelEvent(
                    "tool",
                    call(
                        "task_steer",
                        {
                            "taskId": task_id,
                            "revision": 1,
                            "text": "New user requirement",
                            "requestComplete": True,
                        },
                    ),
                )

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        first = await runtime.chat.submit("alice", c["id"], "lookup", "查一下资料")
        await completed(store, first["turnId"])
        task = (await runtime.tasks.list("alice", c["id"]))[0]
        assert task["revision"] == 1 and task["state"] == "queued"
        assert not await store.call(
            lambda db: rows(db, "SELECT * FROM jobs WHERE kind='task.steer'")
        )
        second = await runtime.chat.submit("alice", c["id"], "status", "刚才的任务完成了吗？")
        await completed(store, second["turnId"])
        assert phase == 6 and len(await runtime.tasks.list("alice", c["id"])) == 1
        third = await runtime.chat.submit("alice", c["id"], "update", "补充这个要求")
        await completed(store, third["turnId"])
        assert phase == 7
        assert (
            len(await store.call(lambda db: rows(db, "SELECT * FROM jobs WHERE kind='task.steer'")))
            == 1
        )
    finally:
        await runtime.close()


async def test_read_then_two_handoffs_in_one_batch_end_without_extra_model_round(store):
    class Main:
        model = "batched-handoff"

        async def stream(self, messages, tools):
            assert messages[-1]["role"] == "user", "Accepted work must not cost another model round"
            yield ModelEvent("tool", call("memory_search", {"query": "preferences"}))
            for index in range(2):
                yield ModelEvent(
                    "tool",
                    call(
                        "delegate",
                        {
                            "goal": f"Requested part {index}",
                            "requestComplete": index == 1,
                        },
                        f"part-{index}",
                    ),
                )

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "both", "分别查两份资料")
        await completed(store, receipt["turnId"])
        assert len(await runtime.tasks.list("alice", c["id"])) == 2
        manifests = await store.call(
            lambda db: rows(
                db, "SELECT * FROM prompt_manifests WHERE turn_id=?", (receipt["turnId"],)
            )
        )
        assert len(manifests) == 1
    finally:
        await runtime.close()


async def test_failed_batch_call_does_not_hide_behind_final_handoff(store):
    rounds = 0

    class Main:
        model = "failed-batch"

        async def stream(self, messages, tools):
            nonlocal rounds
            rounds += 1
            if rounds == 1:
                yield ModelEvent("tool", call("missing_operation", {}))
                yield ModelEvent(
                    "tool", call("delegate", {"goal": "Other part", "requestComplete": True})
                )
            else:
                assert "TOOL_UNAVAILABLE" in str(messages)
                yield ModelEvent("text", "一项已安排，另一项暂不支持。")

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "both", "处理这两项")
        await completed(store, receipt["turnId"])
        assert rounds == 2 and len(await runtime.tasks.list("alice", c["id"])) == 1
    finally:
        await runtime.close()


async def test_model_repairs_missing_flag_without_duplicating_dispatch(store):
    rounds = 0

    class Main:
        model = "missing-flag-repair"

        async def stream(self, messages, tools):
            nonlocal rounds
            rounds += 1
            if rounds == 2:
                rejected = json.loads(messages[-1]["content"])
                assert rejected["executionStarted"] is False
                assert rejected["missingFields"] == ["requestComplete"]
            assert rounds <= 2
            yield ModelEvent(
                "tool",
                call(
                    "delegate",
                    {
                        "goal": "The exact original request",
                        **({"requestComplete": True} if rounds == 2 else {}),
                    },
                    f"dispatch-{rounds}",
                ),
            )

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit(
            "alice", c["id"], "lookup", "The exact original request"
        )
        await completed(store, receipt["turnId"])
        tasks = await runtime.tasks.list("alice", c["id"])
        assert (
            len(tasks) == 1
            and json.loads(tasks[0]["intent_json"])["goal"] == "The exact original request"
        )
        assert rounds == 2
    finally:
        await runtime.close()


async def test_externalized_receipt_preserves_handoff_control_fields():
    from roami_agent.protocol.tools import Tool, object_schema
    from roami_agent.tools.registry import Tools

    class Artifacts:
        async def put(self, owner, body, **metadata):
            return {"id": "receipt", "name": metadata["name"]}

    async def accept(args, binding):
        return {
            "acceptedOnly": True,
            "requestComplete": True,
            "taskId": "task",
            "text": "x" * 130_000,
        }

    tools = Tools(Artifacts())
    tools.add(Tool("delegate", "Large receipt", object_schema({}), accept, main=True))
    receipt = await tools.invoke(call("delegate", {}), "main", {"owner": "alice"})
    assert receipt["outputExternalized"] is True
    assert receipt["acceptedOnly"] is True and receipt["requestComplete"] is True
    assert receipt["taskId"] == "task"


async def test_unscoped_status_can_discover_other_requested_tasks_after_handoff(store):
    other_id = None
    rounds = 0

    class Main:
        model = "lookup-and-other-status"

        async def stream(self, messages, tools):
            nonlocal rounds
            rounds += 1
            if rounds == 1:
                yield ModelEvent(
                    "tool", call("delegate", {"goal": "New lookup", "requestComplete": False})
                )
            elif rounds == 2:
                yield ModelEvent("tool", call("task_status", {}))
            else:
                status = json.loads(messages[-1]["content"])
                assert [item["id"] for item in status] == [other_id]
                yield ModelEvent("text", "新的查询已安排，之前的任务还在排队。")

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        other = await runtime.tasks.create(
            "alice", c["id"], "Previous work", key="previous", record_intent=True
        )
        other_id = other["id"]
        receipt = await runtime.chat.submit(
            "alice", c["id"], "mixed", "查新资料，再看看之前那个任务"
        )
        await completed(store, receipt["turnId"])
        assert rounds == 3 and len(await runtime.tasks.list("alice", c["id"])) == 2
    finally:
        await runtime.close()


@pytest.mark.parametrize("include_result", [False, True])
async def test_status_progress_guidance_preserves_explicit_full_result_requests(
    store, include_result
):
    from test_task_delivery_benchmark import mark

    report = "Full executor evidence, sources and limitations. " * 3500
    task_id = None
    rounds = 0

    class Main:
        model = "progress-or-results"

        async def stream(self, messages, tools):
            nonlocal rounds
            rounds += 1
            if rounds == 1:
                yield ModelEvent(
                    "tool",
                    call("task_status", {"taskId": task_id, "includeResult": include_result}),
                )
            else:
                assert messages[-1]["role"] == "tool"
                assert any(
                    m["role"] == "system" and m["content"].startswith("Task response scope:")
                    for m in messages
                )
                status = json.loads(messages[-1]["content"])[0]
                if include_result:
                    assert status["executorResult"]["summary"] == report
                    assert "OLD_ASSISTANT_TABLE" in str(messages)
                else:
                    assert "executorResult" not in status
                    assert "OLD_ASSISTANT_TABLE" not in str(messages)
                    assert "Full executor evidence" not in str(messages)
                yield ModelEvent("text", report if include_result else "完成了。")

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    try:
        c = await runtime.conversations.create("alice")
        from roami_agent.storage.transcript_repository import message

        await store.call(
            lambda db: message(
                db, c["id"], c["active_branch_id"], "assistant", {"text": "OLD_ASSISTANT_TABLE"}
            ),
            write=True,
        )
        task = await runtime.tasks.create(
            "alice", c["id"], "Prior lookup", key="prior", record_intent=True
        )
        task_id = task["id"]
        await mark(runtime, task, "succeeded", {"state": "succeeded", "summary": report})
        await runtime.start()
        receipt = await runtime.chat.submit(
            "alice", c["id"], "status", "Full results, please" if include_result else "Finished?"
        )
        await completed(store, receipt["turnId"])
        assert rounds == 2
        await store.call(
            lambda db: db.execute("UPDATE tasks SET revision=2 WHERE id=?", (task_id,)), write=True
        )
        snapshot = await runtime.tools.registry["task_status"].handler(
            {"taskId": task_id, "includeResult": True},
            {"owner": "alice", "conversation": c["id"], "turnId": receipt["turnId"]},
        )
        assert snapshot[0]["executorResult"] is None
    finally:
        await runtime.close()
