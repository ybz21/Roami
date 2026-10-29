"""Downloadable files must not let a completion callback omit its actual findings."""

import json

import pytest
from test_coordinator_handoff import call
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.models import ModelEvent
from roami_agent.replies.delivery_policy import COMPLETION_REPORT_INSTRUCTIONS
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


@pytest.mark.parametrize("state", ["waiting_user", "succeeded", "failed"])
@pytest.mark.parametrize("attachment_task", ["same", "other"])
async def test_file_callback_requires_findings_even_with_a_downloadable_attachment(
    store, state, attachment_task
):
    rounds, task_id = 0, None
    outcome = {
        "waiting_user": "报告已生成，结论是记录完整，仍待验收。",
        "succeeded": "报告已完成并通过核验，结论是记录完整。",
        "failed": "报告已生成，但完整性核验失败，结果尚未确认。",
    }[state]

    class Main:
        model = "file-completion-summary-fixture"

        async def stream(self, messages, tools):
            nonlocal rounds
            rounds += 1
            assert "file links alone are not a summary" in messages[0]["content"]
            assert "For pure task progress/completion use task_reply" not in messages[0]["content"]
            assert "task_reply suffices only when verified file links" not in messages[0]["content"]
            assert COMPLETION_REPORT_INSTRUCTIONS in messages[0]["content"]
            assert any(
                message["role"] == "system"
                and COMPLETION_REPORT_INSTRUCTIONS in message["content"]
                and "Background task result." in message["content"]
                for message in messages[1:]
            )
            if rounds == 1:
                yield ModelEvent("tool", call("task_reply", {"taskId": task_id}))
            else:
                assert rounds == 2
                assert json.loads(messages[-1]["content"])["error"] == "TASK_RESULT_REQUIRED"
                yield ModelEvent("tool", call("reply", {"text": outcome}))

    runtime = Runtime(store, Main(), settings=Settings(workers=0), memory_model=ConversationModel())
    try:
        c = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", c["id"], "生成报告并说明结论", key="report", record_intent=True
        )
        task_id = task["id"]
        attempt = await store.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task_id,))
        )
        destination = task
        if attachment_task == "other":
            destination = await runtime.tasks.create(
                "alice", c["id"], "另一份报告", key="other", record_intent=True
            )
        artifact = await runtime.artifacts.put(
            "alice",
            b"report body",
            name="report.txt",
            mime_type="text/plain",
            task_id=destination["id"],
            metadata={"source": "native_result", "runId": attempt["id"]},
        )
        await runtime.dispatch.complete(
            task,
            attempt,
            {"state": "succeeded", "summary": outcome, "artifactRefs": [artifact]},
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
        await runtime.loop.run(
            turn, "main", completion=json.loads(job["payload_json"])["completion"]
        )
        transcript = await runtime.conversations.messages("alice", c["id"])
        reply = transcript["messages"][-1]["content"]["text"]
        assert outcome in reply and rounds == 2
        assert (await runtime.tasks.get("alice", task_id))["task"]["state"] == state
        if attachment_task == "same" and state in {"succeeded", "waiting_user"}:
            assert artifact["downloadUrl"] in reply
        if attachment_task == "other":
            assert artifact["downloadUrl"] not in reply
        assert len(await runtime.tasks.list("alice", c["id"])) == (
            1 if attachment_task == "same" else 2
        )
    finally:
        await runtime.close()
