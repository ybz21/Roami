"""A completion receipt cannot reopen a request already handed off by Main."""

import json

import pytest
from test_coordinator_handoff import call
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row, rows


@pytest.mark.parametrize("handoff", ["delegate", "task_steer"])
@pytest.mark.parametrize("operation", ["delegate", "task_steer", "task_steer_cli"])
@pytest.mark.parametrize("state", ["succeeded", "waiting_user", "failed", "interrupted"])
async def test_final_user_handoff_blocks_callback_replacement_but_allows_new_user_followup(
    store, handoff, operation, state
):
    task_id, phase = None, 0

    class Main:
        model = "followup-callback-admission"

        async def stream(self, messages, tools):
            nonlocal phase
            phase += 1
            if phase in {1, 4}:
                assert messages[-1]["role"] == "user"
                assert messages[-1]["content"] == "补上边界条件说明。"
                name = handoff if phase == 1 else "task_steer"
                args = (
                    {"goal": "补上边界条件说明。", "requestComplete": True}
                    if name == "delegate"
                    else {
                        "taskId": task_id,
                        "revision": 1 if phase == 1 else 2 if handoff == "task_steer" else 1,
                        "text": "补上边界条件说明。",
                        "sourceQuote": "补上边界条件说明。",
                        "requestComplete": True,
                    }
                )
                yield ModelEvent("tool", call(name, args))
            elif phase == 2:
                args = (
                    {"goal": "Repair again in another task", "requestComplete": True}
                    if operation == "delegate"
                    else {
                        "taskId": task_id,
                        "revision": 2 if handoff == "task_steer" else 1,
                        "text": "Repair again without another user request",
                        "requestComplete": True,
                    }
                )
                yield ModelEvent(
                    "tool",
                    call(
                        "delegate" if operation == "delegate" else "task_steer",
                        args,
                        cli=operation == "task_steer_cli",
                    ),
                )
            else:
                assert phase == 3
                rejection = json.loads(messages[-1]["content"])
                assert rejection["error"] == "TASK_COMPLETION_RESTART_FORBIDDEN"
                assert "not a new user" in rejection["recovery"]
                yield ModelEvent("text", "本轮结果已返回，请核对执行记录。")

    runtime = Runtime(
        store,
        Main(),
        worker_model=ConversationModel(),
        memory_model=ConversationModel(),
        settings=Settings(workers=0),
    )
    directory = runtime.tools.directory
    runtime.tools.directory = None
    try:
        conversation = await runtime.conversations.create("alice")
        if handoff == "task_steer":
            original = await runtime.tasks.create(
                "alice", conversation["id"], "Original work", key="original", record_intent=True
            )
            task_id = original["id"]
            await store.call(
                lambda db: db.execute("UPDATE tasks SET state='succeeded' WHERE id=?", (task_id,)),
                write=True,
            )
            await store.call(
                lambda db: db.execute(
                    "UPDATE task_attempts SET state='succeeded',result_json=? WHERE task_id=?",
                    (json.dumps({"state": "succeeded", "inputStopped": True}), task_id),
                ),
                write=True,
            )

        async def user_turn(key):
            receipt = await runtime.chat.submit(
                "alice", conversation["id"], key, "补上边界条件说明。"
            )
            job = await store.call(
                lambda db: row(db, "SELECT * FROM jobs WHERE aggregate_id=?", (receipt["turnId"],))
            )
            turn = await runtime.mailbox.claim(job)
            await runtime.loop.run(turn, "main")
            return receipt

        source = await user_turn("followup")
        await runtime.tasks.revisions.advance()
        task = (await runtime.tasks.list("alice", conversation["id"]))[0]
        task_id = task["id"]
        revision = 2 if handoff == "task_steer" else 1
        assert task["revision"] == revision
        attempt = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=?",
                (task_id, revision),
            )
        )
        await runtime.dispatch.complete(
            task,
            attempt,
            {"state": "succeeded", "summary": "边界条件说明", "inputStopped": True},
            state,
        )
        job = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE kind='turn.run' AND json_extract(payload_json,'$.completion.taskId')=?",
                (task_id,),
            )
        )
        turn = await runtime.mailbox.claim(job)
        if operation == "task_steer_cli":
            runtime.tools.directory = directory
        await runtime.loop.run(
            turn, "main", completion=json.loads(job["payload_json"])["completion"]
        )
        runtime.tools.directory = None
        tasks = await runtime.tasks.list("alice", conversation["id"])
        assert len(tasks) == 1 and tasks[0]["revision"] == revision
        assert tasks[0]["state"] == state
        assert phase == 3
        transcript = await runtime.conversations.messages("alice", conversation["id"])
        assert transcript["messages"][-1]["content"]["text"] == "本轮结果已返回，请核对执行记录。"
        calls = await store.call(
            lambda db: rows(db, "SELECT * FROM tool_calls WHERE turn_id=?", (source["turnId"],))
        )
        assert len(calls) == 1 and calls[0]["state"] == "succeeded"

        await user_turn("fresh-followup")
        await runtime.tasks.revisions.advance()
        tasks = await runtime.tasks.list("alice", conversation["id"])
        assert len(tasks) == 1 and tasks[0]["revision"] == revision + 1
        assert phase == 4
    finally:
        await runtime.close()


async def test_nonfinal_user_handoff_keeps_authorized_next_stage(store):
    phase = 0

    class Main:
        model = "staged-handoff"

        async def stream(self, messages, tools):
            nonlocal phase
            phase += 1
            if phase in {1, 3}:
                yield ModelEvent(
                    "tool",
                    call(
                        "delegate",
                        {
                            "goal": "First stage" if phase == 1 else "Second stage",
                            "requestComplete": phase == 3,
                        },
                    ),
                )
            else:
                assert phase == 2
                yield ModelEvent("text", "先处理第一项。")

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    runtime.tools.directory = None
    try:
        conversation = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit(
            "alice", conversation["id"], "stages", "先整理第一项，再处理第二项。"
        )
        job = await store.call(
            lambda db: row(db, "SELECT * FROM jobs WHERE aggregate_id=?", (receipt["turnId"],))
        )
        turn = await runtime.mailbox.claim(job)
        await runtime.loop.run(turn, "main")
        first = (await runtime.tasks.list("alice", conversation["id"]))[0]
        attempt = await store.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (first["id"],))
        )
        await runtime.dispatch.complete(first, attempt, {"state": "succeeded"}, "succeeded")
        job = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE kind='turn.run' AND json_extract(payload_json,'$.completion.taskId')=?",
                (first["id"],),
            )
        )
        turn = await runtime.mailbox.claim(job)
        await runtime.loop.run(
            turn, "main", completion=json.loads(job["payload_json"])["completion"]
        )
        tasks = await runtime.tasks.list("alice", conversation["id"])
        assert len(tasks) == 2 and phase == 3
        assert {task["origin_message_id"] for task in tasks} == {receipt["messageId"]}
    finally:
        await runtime.close()
