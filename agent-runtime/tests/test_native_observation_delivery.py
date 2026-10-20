"""Observation captures stay internal unless the executor reports them as outputs."""

import json

import pytest
from test_runtime import until

from roami_agent.app import Runtime
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.database import row


@pytest.mark.parametrize(
    "source,explicit,capture_count,normal_output",
    [
        ("browser", False, 1, False),
        ("browser", True, 1, False),
        ("computer", False, 1, False),
        ("computer", True, 1, False),
        ("browser", False, 30, True),
    ],
)
async def test_internal_capture_is_retained_without_becoming_a_default_attachment(
    store, source, explicit, capture_count, normal_output
):
    class Main:
        model = "plain-delivery"

        async def stream(self, messages, tools):
            yield ModelEvent("text", "查询完成。")

    class Worker:
        model = "observed-page"

        async def stream(self, messages, tools):
            mid = await store.call(
                lambda db: row(
                    db,
                    "SELECT id FROM messages WHERE branch_id=? AND role='assistant' ORDER BY seq DESC LIMIT 1",
                    (run["native_branch_id"],),
                )
            )
            if normal_output:
                await runtime.artifacts.put(
                    "alice",
                    b"report",
                    name="report.txt",
                    mime_type="text/plain",
                    task_id=task["id"],
                    message_id=mid["id"],
                    metadata={"source": "native_result"},
                )
            for index in range(capture_count):
                capture = await runtime.artifacts.put(
                    "alice",
                    b"capture" + str(index).encode(),
                    name="observation.png",
                    mime_type="image/png",
                    task_id=task["id"],
                    message_id=mid["id"],
                    metadata={"source": source},
                )
            yield ModelEvent(
                "text", "来源已核对。" + (f" [截图]({capture['downloadUrl']})" if explicit else "")
            )

    async def verifier(task, result):
        return True

    runtime = Runtime(store, Main(), worker_model=Worker(), verifier=verifier)
    try:
        c = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            c["id"],
            "保存报告" if normal_output else "给我截图" if explicit else "查看天气",
            key="observation",
            record_intent=True,
        )
        run = await store.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
        )
        await runtime.start()
        await until(
            store,
            lambda db: row(
                db,
                "SELECT id FROM turns WHERE conversation_id=? AND trigger_kind='completion' AND state='completed'",
                (c["id"],),
            ),
        )
        captures = await runtime.artifacts.list("alice", task_id=task["id"])
        assert len(captures) == capture_count + int(normal_output)
        capture = next(item for item in captures if item["name"] == "observation.png")
        assert (await runtime.artifacts.read("alice", capture["id"]))[1].startswith(b"capture")
        messages = (await runtime.conversations.messages("alice", c["id"]))["messages"]
        delivered = messages[-1]["content"]["text"]
        result = json.loads(
            (
                await store.call(
                    lambda db: row(
                        db, "SELECT result_json FROM task_attempts WHERE id=?", (run["id"],)
                    )
                )
            )["result_json"]
        )
        assert "unavailableOutputs" not in result
        if normal_output:
            output = next(item for item in captures if item["name"] == "report.txt")
            assert output["downloadUrl"] in delivered
            assert [item["id"] for item in result["artifactRefs"]] == [output["id"]]
        elif explicit:
            assert capture["downloadUrl"] in delivered
            assert result["artifactRefs"][0]["id"] == capture["id"]
        else:
            assert delivered == "查询完成。"
            assert "artifactRefs" not in result
    finally:
        await runtime.close()
