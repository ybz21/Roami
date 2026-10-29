import json
import sys

import pytest
from native_prompt_messages import dialogue_messages

from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.tools.registry import Tools
from roami_agent.tools.shell import register_shell


@pytest.mark.parametrize(
    "method,filename",
    [
        ("write", "summary.txt"),
        ("shell", "summary.txt"),
        ("shell-only", "summary.txt"),
        ("write", "answer.py"),
        ("shell-only", "answer.py"),
    ],
)
async def test_created_file_is_delivered_even_when_worker_and_main_omit_links(
    store, tmp_path, method, filename
):
    from contextlib import asynccontextmanager

    from test_runtime import until

    from roami_agent.app import Runtime
    from roami_agent.protocol.models import ModelEvent
    from roami_agent.storage.database import row

    workspace = tmp_path / "work with spaces"
    workspace.mkdir()

    class Main:
        model = "bare-main-report"

        async def stream(self, messages, tools):
            evidence = next(
                (
                    m["content"].split("Executor evidence: ", 1)[1]
                    for m in messages
                    if isinstance(m.get("content"), str) and "Executor evidence: " in m["content"]
                ),
                None,
            )
            if filename.endswith(".py") and evidence:
                completion = json.JSONDecoder().raw_decode(evidence)[0]
                yield ModelEvent(
                    "tool",
                    {
                        "id": "deliver",
                        "function": {
                            "name": "task_reply",
                            "arguments": json.dumps({"taskId": completion["taskId"]}),
                        },
                    },
                )
                return
            yield ModelEvent("text", "File saved.")

    class Worker:
        model = "bare-worker-report"

        async def stream(self, messages, tools):
            observed = sum(m["role"] == "tool" for m in messages)
            if method in {"shell", "shell-only"} and observed == 0:
                yield ModelEvent(
                    "tool",
                    {
                        "id": "save",
                        "function": {
                            "name": "bash",
                            "arguments": json.dumps(
                                {
                                    "argv": [
                                        sys.executable,
                                        "-c",
                                        f"from pathlib import Path; Path({filename!r}).write_text('验收完成')",
                                    ]
                                }
                            ),
                        },
                    },
                )
            elif method == "shell" and observed == 1:
                yield ModelEvent(
                    "tool",
                    {
                        "id": "readback",
                        "function": {
                            "name": "read",
                            "arguments": json.dumps({"path": filename}),
                        },
                    },
                )
            elif observed:
                yield ModelEvent(
                    "text",
                    f"验收完成，文件 {workspace / filename} 已保存。"
                    if method == "shell-only"
                    else f"验收完成，文件 {filename} 已保存。",
                )
            else:
                yield ModelEvent(
                    "tool",
                    {
                        "id": "save",
                        "function": {
                            "name": "write",
                            "arguments": json.dumps(
                                {
                                    "path": filename,
                                    "expectedSha256": None,
                                    "content": "验收完成",
                                }
                            ),
                        },
                    },
                )

    @asynccontextmanager
    async def prepare(*args, **kwargs):
        yield {"workspaceId": "fixture", "directory": str(workspace)}

    runtime = Runtime(store, Main(), worker_model=Worker(), memory_model=Main())
    runtime.dispatch.native_executor.workspace_factory = prepare
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            conversation["id"],
            f"Save {filename}",
            key="save",
            target={"kind": "new_session", "directory": str(workspace)},
            record_intent=True,
        )
        runtime.wakeup.set()
        await until(
            store,
            lambda db: row(
                db,
                "SELECT id FROM turns WHERE conversation_id=? AND trigger_kind='completion' AND state='completed'",
                (conversation["id"],),
            ),
        )
        references = await runtime.artifacts.list("alice", task_id=task["id"])
        assert len(references) == 1 and references[0]["name"] == filename
        messages = (await runtime.conversations.messages("alice", conversation["id"]))["messages"]
        assert references[0]["downloadUrl"] in messages[-1]["content"]["text"]
        (workspace / filename).unlink()
        if filename.endswith(".py"):
            assert not await store.call(
                lambda db: row(
                    db, "SELECT id FROM tool_calls WHERE state='failed' AND tool_name='task_reply'"
                )
            )
        assert (await runtime.artifacts.read("alice", references[0]["id"]))[
            1
        ].decode() == "验收完成"
        with pytest.raises(DomainError, match="ARTIFACT_NOT_FOUND"):
            await runtime.artifacts.read("bob", references[0]["id"])
    finally:
        await runtime.close()


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


@pytest.mark.parametrize("role", ["main", "worker"])
async def test_multistep_turn_does_not_sum_individual_model_request_timeouts(store, role):
    import asyncio
    from dataclasses import replace

    from test_runtime import ConversationModel, until

    from roami_agent.app import Runtime
    from roami_agent.protocol.models import ModelEvent
    from roami_agent.storage.database import row

    class MultiStepWorker:
        model = "multi-step-worker"

        async def stream(self, messages, tools):
            messages = dialogue_messages(messages)
            await asyncio.sleep(0.6)
            if messages[-1]["role"] == "tool":
                yield ModelEvent("text", "verified work")
            else:
                yield ModelEvent(
                    "tool",
                    {
                        "id": "load-workflow",
                        "function": {
                            "name": "read",
                            "arguments": json.dumps({"path": "skill://browser_use"}),
                        },
                    },
                )

    runtime = Runtime(
        store,
        MultiStepWorker() if role == "main" else ConversationModel(),
        worker_model=MultiStepWorker(),
        settings=replace(Settings(), timeout_seconds=1),
    )
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        if role == "main":
            receipt = await runtime.chat.submit(
                "alice", conversation["id"], "multi-step-budget", "work"
            )
            await until(
                store,
                lambda db: row(
                    db,
                    "SELECT id FROM turns WHERE id=? AND state='completed'",
                    (receipt["turnId"],),
                ),
            )
        else:
            task = await runtime.tasks.create(
                "alice", conversation["id"], "work", key="multi-step-budget", record_intent=True
            )
            await until(
                store,
                lambda db: row(
                    db, "SELECT id FROM tasks WHERE id=? AND state='succeeded'", (task["id"],)
                ),
            )
    finally:
        await runtime.close()


async def test_native_task_carries_original_attachment_and_honors_artifact_deletion(store):
    from test_runtime import ConversationModel

    from roami_agent.app import Runtime
    from roami_agent.storage.database import row

    runtime = Runtime(store, ConversationModel())
    try:
        conversation = await runtime.conversations.create("alice")
        attachment = await runtime.attachments.upload(
            "alice", "batches.csv", "batch-source", b"requests,successes\n1000,992\n2000,1970\n"
        )
        receipt = await runtime.chat.submit(
            "alice",
            conversation["id"],
            "review-batches",
            "Review the uploaded batches",
            [attachment["id"]],
        )
        task = await runtime.tasks.create(
            "alice",
            conversation["id"],
            "Analyze the batches",
            key="attachment-worker",
            origin_message_id=receipt["messageId"],
        )
        child = await store.call(
            lambda db: row(
                db,
                "SELECT b.conversation_id,b.id FROM branches b JOIN task_attempts a ON a.native_branch_id=b.id WHERE a.task_id=?",
                (task["id"],),
            )
        )
        plan = await runtime.context.project(
            "alice", child["conversation_id"], branch_id=child["id"]
        )
        assert "1000,992" in json.dumps(plan)
        assert plan["attachmentEvidence"][0]["artifactId"] == attachment["id"]
        await runtime.artifacts.delete("alice", attachment["id"])
        plan = await runtime.context.project(
            "alice", child["conversation_id"], branch_id=child["id"]
        )
        assert not plan["attachmentEvidence"]
        assert "1000,992" not in json.dumps(plan)
    finally:
        await runtime.close()


async def test_native_task_deadline_still_cancels_before_late_effects():
    import asyncio

    from roami_agent.executors.native import NativeExecutor
    from roami_agent.protocol.identity import now_ms

    wrote = False

    async def worker(turn, role, *, task_id):
        nonlocal wrote
        assert 0 <= turn["executionTimeoutSeconds"] <= 0.1
        await asyncio.sleep(1)
        wrote = True
        return "late effect"

    executor = NativeExecutor(worker)
    task = {
        "id": "deadline-task",
        "owner_id": "alice",
        "intent_json": json.dumps({"target": {"kind": "new_session"}}),
        "budget_json": json.dumps({"deadlineMs": now_ms() + 30}),
    }
    with pytest.raises(TimeoutError):
        await executor.run(
            task, {"id": "run", "native_branch_id": "branch"}, turn={"branch_id": "branch"}
        )
    assert not wrote
