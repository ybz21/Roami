import json
import sys

import pytest

from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.tools.registry import Tools
from roami_agent.tools.shell import register_shell


async def test_bound_shell_uses_workspace_default_and_relative_paths_and_rejects_other_roots(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("GIT_DIR", "/foreign/repository")
    monkeypatch.setenv("GIT_SSH_COMMAND", "preserved-auth")
    workspace = tmp_path / "prepared"
    workspace.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    registry = Tools()
    register_shell(registry, Settings(shell_roots=(tmp_path,)))

    def call(cwd=None):
        args = {
            "argv": [
                sys.executable,
                "-c",
                "import os; assert 'GIT_DIR' not in os.environ; assert os.environ['GIT_SSH_COMMAND'] == 'preserved-auth'; print(os.getcwd())",
            ]
        }
        if cwd is not None:
            args["cwd"] = cwd
        return {"function": {"name": "shell", "arguments": json.dumps(args)}}

    binding = {"workspace": {"directory": str(workspace)}}
    for cwd in [None, "."]:
        result = await registry.invoke(call(cwd), "worker", binding)
        assert result["stdout"].strip() == str(workspace)
    for cwd in [str(other), "../other"]:
        with pytest.raises(DomainError, match="WORKSPACE_OUTSIDE_CONFIGURED_ROOTS"):
            await registry.invoke(call(cwd), "worker", binding)
    assert (await registry.invoke(call(str(other)), "worker", {}))["stdout"].strip() == str(other)
    with pytest.raises(DomainError, match="WORKSPACE_REQUIRED"):
        await registry.invoke(call(), "worker", {})
    with pytest.raises(DomainError, match="TASK_WORKSPACE_REQUIRED"):
        await registry.invoke(call(str(other)), "worker", {"taskId": "unprepared"})


@pytest.mark.parametrize("action", ["cancel", "forget"])
async def test_preparation_cancellation_or_forgotten_origin_never_reaches_worker(
    store, tmp_path, action
):
    import asyncio
    from contextlib import asynccontextmanager

    from test_runtime import ConversationModel, until

    from roami_agent.app import Runtime
    from roami_agent.storage.database import row

    class NeverWorker:
        model = "never-admitted-worker"

        async def stream(self, messages, tools):
            pytest.fail("Worker saw an invalidated preparation")
            yield

    runtime = Runtime(
        store, ConversationModel(), worker_model=NeverWorker(), memory_model=ConversationModel()
    )
    entered, release, cleaned = asyncio.Event(), asyncio.Event(), asyncio.Event()

    @asynccontextmanager
    async def prepare(settings, task, run, *, stopped):
        entered.set()
        try:
            await release.wait()
            yield {"workspaceId": "fixture", "directory": str(tmp_path), "projectId": "project"}
        finally:
            assert await stopped()
            cleaned.set()

    runtime.dispatch.native_executor.workspace_factory = prepare
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            c["id"],
            "project work",
            key="pending-preparation",
            target={"kind": "project", "projectId": "project"},
            record_intent=True,
        )
        await asyncio.wait_for(entered.wait(), 3)
        if action == "cancel":
            await runtime.tasks.cancel("alice", task["id"])
        else:
            memory = await runtime.memory.save(
                "alice", "private", "project work", task["origin_message_id"]
            )
            await runtime.memory.forget("alice", memory["id"])
            release.set()
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM tasks WHERE id=? AND state='cancelled'", (task["id"],)
            ),
        )
        assert cleaned.is_set()
        assert not await store.call(
            lambda db: row(
                db,
                "SELECT t.id FROM turns t JOIN task_attempts a ON a.native_branch_id=t.branch_id WHERE a.task_id=? AND t.state='running'",
                (task["id"],),
            )
        )
    finally:
        await runtime.close()


async def test_long_native_result_keeps_full_source_and_bounded_completion_evidence(store):
    from test_runtime import ConversationModel, until

    from roami_agent.app import Runtime
    from roami_agent.protocol.models import ModelEvent
    from roami_agent.storage.database import row

    full = "完整任务结果" * 2000

    class LongResult:
        model = "long-native-result"

        async def stream(self, messages, tools):
            yield ModelEvent("text", full)

    runtime = Runtime(store, ConversationModel(), worker_model=LongResult())
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            conversation["id"],
            "Return the detailed result",
            key="long-result",
            record_intent=True,
        )
        runtime.wakeup.set()
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM tasks WHERE id=? AND state='succeeded'", (task["id"],)
            ),
        )
        attempt = await store.call(
            lambda db: row(
                db, "SELECT result_json FROM task_attempts WHERE task_id=?", (task["id"],)
            )
        )
        result = json.loads(attempt["result_json"])
        assert result["summaryTruncated"] and len(result["summary"].encode()) <= 6000
        source = await store.call(
            lambda db: row(
                db,
                "SELECT content_json FROM messages WHERE id=?",
                (result["resultRef"]["messageId"],),
            )
        )
        assert json.loads(source["content_json"])["text"] == full
        reference = result["artifactRefs"][0]
        assert reference["name"] == "task-result.txt"
        assert (await runtime.artifacts.read("alice", reference["id"]))[1].decode() == full
    finally:
        await runtime.close()


async def test_unknown_write_cannot_be_overridden_by_worker_summary_or_goal_verifier(store):
    from test_runtime import ConversationModel, until

    from roami_agent.app import Runtime
    from roami_agent.protocol.models import ModelEvent
    from roami_agent.protocol.tools import Tool, object_schema
    from roami_agent.storage.database import row

    class OptimisticWorker:
        model = "optimistic-worker"

        async def stream(self, messages, tools):
            if messages[-1]["role"] == "tool":
                assert json.loads(messages[-1]["content"])["outcomeKnown"] is False
                yield ModelEvent("text", "Everything is done")
            else:
                yield ModelEvent(
                    "tool",
                    {
                        "id": "unknown-write",
                        "type": "function",
                        "function": {"name": "uncertain_write", "arguments": "{}"},
                    },
                )

    async def unknown_write(args, binding):
        raise DomainError("TOOL_OUTCOME_UNKNOWN")

    async def verifier(task, result):
        pytest.fail("An unknown write reached goal acceptance")

    runtime = Runtime(
        store,
        ConversationModel(),
        worker_model=OptimisticWorker(),
        verifier=verifier,
        memory_model=ConversationModel(),
    )
    runtime.tools.add(
        Tool(
            "uncertain_write",
            "Unknown fixture write",
            object_schema({}),
            unknown_write,
            effect="write",
        )
    )
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            conversation["id"],
            "Perform the write",
            key="unknown-summary",
            record_intent=True,
        )
        runtime.wakeup.set()
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM tasks WHERE id=? AND state='interrupted'", (task["id"],)
            ),
        )
        attempt = await store.call(
            lambda db: row(
                db, "SELECT result_json FROM task_attempts WHERE task_id=?", (task["id"],)
            )
        )
        assert json.loads(attempt["result_json"])["outcomeKnown"] is False
    finally:
        await runtime.close()
