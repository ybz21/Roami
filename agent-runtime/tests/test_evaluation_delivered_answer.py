"""Native evaluation grades the delivered answer bound to its request, never a convenient number."""

import json
from types import SimpleNamespace

import pytest
from test_runtime import until

from roami_agent.app import Runtime
from roami_agent.improvement.evaluation.execution.evaluation_tasks import (
    bind_evaluation_tasks,
    delivered_evaluation_answer,
)
from roami_agent.improvement.evaluation.execution.executors import NativeFilesExecutor
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


class Memory:
    model = "empty-memory"

    async def stream(self, messages, tools):
        yield ModelEvent("text", '{"memories":[]}')


class Worker:
    model = "native-answer"

    async def stream(self, messages, tools):
        yield ModelEvent("text", "0.046")


class Main:
    model = "delivery-main"

    def __init__(self, directory, tasks=1):
        self.calls, self.directory, self.tasks = 0, str(directory), tasks

    async def stream(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            for index in range(self.tasks):
                yield ModelEvent(
                    "tool",
                    {
                        "id": f"delegate-{index}",
                        "function": {
                            "name": "delegate",
                            "arguments": json.dumps(
                                {
                                    "executor": "native",
                                    "goal": f"Compute requested ratio {index}",
                                    "directory": self.directory,
                                }
                            ),
                        },
                    },
                )
        else:
            yield ModelEvent("text", "Queued; result pending." if self.calls == 2 else "0.046")


@pytest.mark.parametrize(
    "mode",
    [
        "valid",
        "wrong_answer",
        "wrong_run",
        "old_revision",
        "other_branch",
        "unfinished",
        "unknown",
        "untyped_answer",
    ],
)
async def test_final_delivery_requires_current_native_attempt_and_completion(store, tmp_path, mode):
    runtime = Runtime(
        store, Main(tmp_path), worker_model=Worker(), memory_model=Memory(), settings=Settings()
    )
    bind_evaluation_tasks(runtime, tmp_path)
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit(
            "alice",
            c["id"],
            "compute",
            "Use Native Worker to compute the ratio in " + str(tmp_path),
        )
        await until(
            store,
            lambda db: row(
                db,
                "SELECT id FROM messages WHERE json_extract(content_json,'$.source')='task' AND json_extract(content_json,'$.answerText') IS NOT NULL",
            ),
        )
        assert await delivered_evaluation_answer(store, receipt["turnId"]) == "0.046"
        other = await runtime.conversations.create("alice")

        def change(db):
            if mode == "wrong_answer":
                db.execute(
                    "UPDATE messages SET content_json=json_set(content_json,'$.answerText','0.1') WHERE json_extract(content_json,'$.source')='task'"
                )
            elif mode == "wrong_run":
                db.execute(
                    "UPDATE jobs SET payload_json=json_set(payload_json,'$.completion.runId','foreign-run') WHERE json_extract(payload_json,'$.completion.taskId') IS NOT NULL"
                )
            elif mode == "old_revision":
                db.execute(
                    "UPDATE jobs SET payload_json=json_set(payload_json,'$.completion.taskRevision',0) WHERE json_extract(payload_json,'$.completion.taskId') IS NOT NULL"
                )
            elif mode == "other_branch":
                db.execute(
                    "UPDATE turns SET branch_id=? WHERE trigger_kind='completion'",
                    (other["active_branch_id"],),
                )
            elif mode == "unfinished":
                db.execute("UPDATE turns SET state='running' WHERE trigger_kind='completion'")
            elif mode == "unknown":
                db.execute(
                    "UPDATE task_attempts SET result_json=json_set(result_json,'$.outcomeKnown',json('false'))"
                )
            elif mode == "untyped_answer":
                db.execute(
                    "UPDATE messages SET content_json=json_set(content_json,'$.answerText',null) WHERE json_extract(content_json,'$.source')='task'"
                )

        await store.call(change, write=True)
        expected = "0.046" if mode == "valid" else "0.1" if mode == "wrong_answer" else None
        assert await delivered_evaluation_answer(store, receipt["turnId"]) == expected
        assert await delivered_evaluation_answer(store, "unrelated-turn") is None
        view = await runtime.conversations.messages("alice", c["id"])
        executor = SimpleNamespace(allow_tasks=True)
        if expected is None:
            with pytest.raises(DomainError, match="RSI_NATIVE_DELIVERY_REQUIRED"):
                await NativeFilesExecutor.answer(
                    executor, store, view["messages"], receipt["turnId"]
                )
        else:
            assert (
                await NativeFilesExecutor.answer(
                    executor, store, view["messages"], receipt["turnId"]
                )
                == expected
            )
        assert (
            await NativeFilesExecutor.answer(
                SimpleNamespace(allow_tasks=False), store, view["messages"], receipt["turnId"]
            )
            == "Queued; result pending."
        )
    finally:
        await runtime.close()


@pytest.mark.parametrize("mode", ["all_delivered", "one_missing", "last_wrong"])
async def test_multiple_handoffs_need_all_deliveries_and_use_last_without_answer_selection(
    store, tmp_path, mode
):
    runtime = Runtime(
        store,
        Main(tmp_path, tasks=2),
        worker_model=Worker(),
        memory_model=Memory(),
        settings=Settings(),
    )
    bind_evaluation_tasks(runtime, tmp_path)
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit(
            "alice", c["id"], "two", "Compute both ratios with Native Worker in " + str(tmp_path)
        )
        await until(
            store,
            lambda db: (
                db.execute(
                    "SELECT count(*) FROM messages WHERE json_extract(content_json,'$.source')='task' AND json_extract(content_json,'$.answerText') IS NOT NULL"
                ).fetchone()[0]
                == 2
            ),
        )
        assert await delivered_evaluation_answer(store, receipt["turnId"]) == "0.046"

        def change(db):
            if mode == "one_missing":
                db.execute(
                    "UPDATE jobs SET payload_json=json_set(payload_json,'$.completion.runId','foreign-run') WHERE id=(SELECT id FROM jobs WHERE json_extract(payload_json,'$.completion.taskId') IS NOT NULL LIMIT 1)"
                )
            elif mode == "last_wrong":
                db.execute(
                    "UPDATE messages SET content_json=json_set(content_json,'$.answerText','0.1') WHERE id=(SELECT id FROM messages WHERE json_extract(content_json,'$.source')='task' ORDER BY rowid DESC LIMIT 1)"
                )

        await store.call(change, write=True)
        assert await delivered_evaluation_answer(store, receipt["turnId"]) == (
            None if mode == "one_missing" else "0.1" if mode == "last_wrong" else "0.046"
        )
    finally:
        await runtime.close()
