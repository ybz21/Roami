"""Professional agents share the registry without escaping task admission or replay guards."""

import asyncio
import base64
import json
import sys
from pathlib import Path

import httpx
import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.context.execution_brief import execution_guide
from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.server.configuration import Settings
from roami_agent.server.http import create_app
from roami_agent.storage.database import row


async def prepared(store, executor="codex"):
    settings = Settings(coding_directory=store.data_root)
    coding = CodingExecutor(store, settings)
    runtime = Runtime(store, ConversationModel(), settings=settings, executor=coding)
    conversation = await runtime.conversations.create("local")
    task = await runtime.tasks.create(
        "local",
        conversation["id"],
        "Use installed capabilities",
        key="professional",
        executor=executor,
        target={"kind": "new_session", "directory": str(store.data_root)},
        record_intent=True,
    )

    def prepare(db):
        db.execute("UPDATE tasks SET state='preparing' WHERE id=?", (task["id"],))
        db.execute("UPDATE task_attempts SET state='starting' WHERE task_id=?", (task["id"],))
        return row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],)), row(
            db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],)
        )

    task, run = await store.call(prepare, write=True)
    launches = []

    async def launch(*args, spec=None):
        launches.append(spec)
        return {
            "state": "running",
            "session": "own-session",
            "workspace": {"directory": str(store.data_root)},
        }

    coding.command = launch
    await coding.run(task, run)
    files = list((store.data_root / "agents/capability-contexts").glob("*.json"))
    assert len(files) == 1 and files[0].stat().st_mode & 0o777 == 0o600
    context = json.loads(files[0].read_text())
    assert context["signature"] not in launches[0]["prompt"]
    prompt = launches[0]["prompt"]
    assert launches[0]["promptFormat"] == "markdown-session"
    assert launches[0]["shortExecutionLabel"] is True
    assert execution_guide() in prompt
    assert prompt.startswith("# 任务：\n\nUse installed capabilities\n\n# 开工准备\n\n")
    assert prompt.index("# 开工准备") < prompt.index("# 执行约定") < prompt.index("# 回报通道")
    assert prompt.index("# 回报通道") < prompt.index("# Roami 本机能力")
    assert "## 产物交付" in prompt and "## 执行结束与通知 Main" in prompt
    assert "downloadUrl" in prompt and "SHA256" in prompt
    assert "任务第 1 版" in prompt
    assert context["taskId"] == task["id"] and context["runId"] == run["id"]
    assert prompt.count(str(files[0])) == 1
    assert prompt.count("```") % 2 == 0
    assert "[Roami platform capabilities]" not in prompt
    assert "roami agent capability" in prompt and "roami --help" in prompt
    assert '--context "$ROAMI_TASK_CONTEXT"' in prompt
    assert "--call REQUEST_ID" in prompt
    return runtime, task, run, context


def request(context, arguments=None, ident="one"):
    return {"executionContext": context, "requestId": ident, "arguments": arguments or {}}


@pytest.mark.parametrize("executor", ["codex", "claude"])
async def test_professional_launch_reads_bundled_skill_and_executes_cli_in_bound_workspace(
    store, executor
):
    runtime, task, _, context = await prepared(store, executor)
    try:
        await runtime.capability_imports.save(
            "local",
            "skills",
            {
                "name": "market-skill",
                "description": "A workflow",
                "text": "Read references/guide.md",
                "files": {"references/guide.md": base64.b64encode(b"retained reference").decode()},
            },
        )
        await runtime.capability_imports.save(
            "local",
            "cli",
            {
                "name": "echo",
                "argv": [sys.executable, "-c", "import os;print(os.getcwd())"],
            },
        )
        transport = httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://agent", headers={"X-Roami-Owner": "local"}
        ) as client:
            skill = await client.post(
                "/v1/tool-directory/skill_read/call",
                json=request(context, {"name": "market-skill"}),
            )
            assert skill.status_code == 200
            value = skill.json()["data"]
            assert value["state"] == "succeeded"
            assert (
                Path(value["result"]["packagePath"], "references/guide.md").read_text()
                == "retained reference"
            )
            reference = await client.post(
                "/v1/tool-directory/skill_read/call",
                json=request(
                    context,
                    {"name": "market-skill", "reference": "references/guide.md"},
                    "reference",
                ),
            )
            assert reference.json()["data"]["result"]["text"] == "retained reference"
            result = await client.post(
                "/v1/tool-directory/cli_echo/call", json=request(context, ident="cli")
            )
            assert result.json()["data"]["state"] == "succeeded"
            assert result.json()["data"]["result"]["stdout"].strip() == str(store.data_root)
        activities = await runtime.tasks.activities("local", task["id"])
        activity = next(a for a in activities if a["name"] == "cli_echo")
        assert activity["state"] == "succeeded" and activity["kind"] == "tool"
        events = await runtime.conversations.events("local", task["origin_conversation_id"])
        streamed = [
            e["payload"]["activity"]
            for e in events
            if e["payload"].get("activity", {}).get("id") == activity["id"]
        ]
        assert [item["state"] for item in streamed] == ["running", "succeeded"]
        assert streamed[0]["preview"]["output"] is None
        assert "stdout" in streamed[1]["preview"]["output"]["text"]
        detail = await runtime.tasks.activities("local", task["id"], activity["id"])
        assert "stdout" in detail["output"]["text"]
        with pytest.raises(DomainError, match="TASK_NOT_FOUND"):
            await runtime.tasks.activities("other", task["id"], activity["id"])
    finally:
        await runtime.close()


async def test_durable_request_deduplication_and_conflicts_survive_bridge_recreation(store):
    from roami_agent.tools.professional_capabilities import ProfessionalCapabilities

    runtime, _, _, context = await prepared(store)
    calls = []

    async def invoke(args, _):
        calls.append(args)
        return {"count": len(calls)}

    runtime.tools.add(
        Tool(
            "market_counter",
            "",
            object_schema({"value": {"type": "integer"}}),
            invoke,
            source="external",
        )
    )
    try:
        payload = request(context, {"value": 1})
        first = await runtime.professional_capabilities.call("market_counter", payload, "local")
        restored = ProfessionalCapabilities(runtime)
        assert await restored.call("market_counter", payload, "local") == first
        assert len(calls) == 1
        with pytest.raises(DomainError, match="CAPABILITY_REQUEST_CONFLICT"):
            await restored.call("market_counter", request(context, {"value": 2}), "local")
        await store.call(
            lambda db: db.execute("DELETE FROM events WHERE kind='capability.completed'"),
            write=True,
        )
        await restored.recover()
        unknown = await restored.call("market_counter", payload, "local")
        assert unknown["state"] == "unknown" and len(calls) == 1
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "condition", ["owner", "signature", "revision", "finished", "forgotten", "steer"]
)
async def test_revoked_or_forged_context_never_executes(store, condition):
    runtime, task, run, context = await prepared(store)
    calls = []

    async def invoke(*_):
        calls.append(True)

    runtime.tools.add(Tool("market_test", "", object_schema({}), invoke, source="external"))
    owner = "local"
    if condition == "owner":
        owner = "other"
    elif condition == "signature":
        context["signature"] = "伪造"
    elif condition == "revision":
        await store.call(
            lambda db: db.execute("UPDATE tasks SET revision=2 WHERE id=?", (task["id"],)),
            write=True,
        )
    elif condition == "finished":
        await store.call(
            lambda db: db.execute(
                "UPDATE task_attempts SET state='succeeded',finished_ms=1 WHERE id=?", (run["id"],)
            ),
            write=True,
        )
    elif condition == "forgotten":
        await store.call(
            lambda db: db.execute(
                "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('local',?,'test',1)",
                (task["origin_message_id"],),
            ),
            write=True,
        )
    else:
        await runtime.tasks.revisions.request("local", task["id"], "Change work", 1, "steer")
    try:
        with pytest.raises(DomainError):
            await runtime.professional_capabilities.call("market_test", request(context), owner)
        assert not calls
    finally:
        await runtime.close()


async def test_disabled_capability_and_outside_workspace_are_rejected(store):
    runtime, _, _, context = await prepared(store)
    try:
        await runtime.capability_imports.save(
            "local",
            "cli",
            {
                "name": "outside",
                "argv": [sys.executable, "-c", "print('must not run')"],
                "cwd": str(store.data_root.parent),
            },
        )
        result = await runtime.professional_capabilities.call(
            "cli_outside", request(context), "local"
        )
        assert result["result"]["error"] == "WORKSPACE_OUTSIDE_CONFIGURED_ROOTS"
        await runtime.capability_settings.save(
            "local", {"kind": "tools", "name": "cli_outside", "enabled": False}
        )
        with pytest.raises(DomainError, match="TOOL_DISABLED"):
            await runtime.professional_capabilities.call(
                "cli_outside", request(context, ident="disabled"), "local"
            )
        with pytest.raises(DomainError, match="TOOL_UNAVAILABLE"):
            await runtime.professional_capabilities.call(
                "shell", request(context, {"argv": ["echo", "bypass"]}), "local"
            )
    finally:
        await runtime.close()


@pytest.mark.parametrize("stop", ["cancel", "close"])
async def test_running_call_is_not_replayed_and_stops_on_task_cancellation_or_shutdown(store, stop):
    runtime, task, _, context = await prepared(store)
    started, stopped = asyncio.Event(), asyncio.Event()

    async def invoke(*_):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    runtime.tools.add(Tool("market_wait", "", object_schema({}), invoke, source="external"))
    operation = asyncio.create_task(
        runtime.professional_capabilities.call("market_wait", request(context), "local")
    )
    try:
        await asyncio.wait_for(started.wait(), 2)
        with pytest.raises(DomainError, match="TOOL_OUTCOME_UNKNOWN"):
            await runtime.professional_capabilities.call("market_wait", request(context), "local")
        if stop == "cancel":
            await runtime.tasks.cancel("local", task["id"])
        else:
            await runtime.professional_capabilities.close()
        result = await asyncio.wait_for(operation, 2)
        assert stopped.is_set() and result["state"] == "unknown"
        activities = await runtime.tasks.activities("local", task["id"])
        assert next(a for a in activities if a["name"] == "market_wait")["state"] == "unknown"
    finally:
        await runtime.close()


async def test_nested_professional_calls_stream_to_the_root_conversation(store):
    runtime, task, _, context = await prepared(store)
    try:
        root = await runtime.conversations.create("local")
        parent = await runtime.tasks.create(
            "local", root["id"], "Parent task", key="parent", record_intent=True
        )
        await store.call(
            lambda db: db.execute(
                "UPDATE tasks SET parent_task_id=? WHERE id=?", (parent["id"], task["id"])
            ),
            write=True,
        )
        await runtime.professional_capabilities.call(
            "skill_read", request(context, {"name": "browser_use"}), "local"
        )
        events = await runtime.conversations.events("local", root["id"])
        steps = [
            event["payload"]["activity"]
            for event in events
            if event["payload"].get("activity", {}).get("name") == "skill_read"
        ]
        assert [step["state"] for step in steps] == ["running", "succeeded"]
        assert steps[1]["taskId"] == task["id"]
        assert "browser_use" in steps[1]["preview"]["input"]["text"]
        assert all(
            event["branchId"] == root["active_branch_id"]
            for event in events
            if event["payload"].get("activityId")
        )
    finally:
        await runtime.close()


@pytest.mark.parametrize("executor", ["codex", "claude"])
async def test_continuation_refreshes_signed_context_without_rebinding_session_or_workspace(
    store, executor
):
    runtime, task, old_run, old_context = await prepared(store, executor)
    try:
        original = json.loads(
            (
                await store.call(
                    lambda db: row(db, "SELECT target_json FROM tasks WHERE id=?", (task["id"],))
                )
            )["target_json"]
        )
        await runtime.capability_imports.save(
            "local",
            "cli",
            {
                "name": "continuation-cwd",
                "argv": [sys.executable, "-c", "import os;print(os.getcwd())"],
            },
        )
        await runtime.tasks.revisions.request(
            "local", task["id"], "Also review the copy boundaries", 1, "continue"
        )
        with pytest.raises(DomainError, match="ACTIVE_TASK_CONTEXT_REQUIRED"):
            await runtime.professional_capabilities.call(
                "skill_read", request(old_context, {"name": "browser_use"}), "local"
            )

        # Model the Go adapter's stop acknowledgement before admitting revision two.
        def stopped(db):
            db.execute("UPDATE tasks SET state='cancelled' WHERE id=?", (task["id"],))
            db.execute(
                "UPDATE task_attempts SET state='cancelled',finished_ms=1,result_json=? WHERE id=?",
                (
                    json.dumps({"state": "cancelled", "inputStopped": True, "outcomeKnown": True}),
                    old_run["id"],
                ),
            )

        await store.call(stopped, write=True)
        await runtime.tasks.revisions.advance()

        def preparing(db):
            db.execute("UPDATE tasks SET state='preparing' WHERE id=?", (task["id"],))
            db.execute(
                "UPDATE task_attempts SET state='starting' WHERE task_id=? AND task_revision=2",
                (task["id"],),
            )
            return row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],)), row(
                db, "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=2", (task["id"],)
            )

        current, new_run = await store.call(preparing, write=True)
        assert current["revision"] == new_run["task_revision"] == 2
        assert new_run["id"] != old_run["id"]
        launches = []

        async def launch(sub, *args, spec=None):
            assert sub == "launch"
            launches.append(spec)
            return {
                "state": "running",
                "session": original["sessionId"],
                "workspace": original["workspace"],
            }

        runtime.executor.command = launch
        await runtime.executor.run(current, new_run)
        files = list((store.data_root / "agents/capability-contexts").glob("*.json"))
        assert len(files) == 2
        current_file = next(
            path for path in files if json.loads(path.read_text())["runId"] == new_run["id"]
        )
        context = json.loads(current_file.read_text())
        assert context["taskId"] == task["id"] and context["revision"] == 2
        assert current_file.stat().st_mode & 0o777 == 0o600
        prompt = launches[0]["prompt"]
        assert str(current_file) in prompt and context["signature"] not in prompt
        assert execution_guide() in prompt
        assert "[文件名](文件绝对路径)" in prompt
        assert "校验工作区范围并复制保存" in prompt
        assert "无需另外调用发布产物接口" in prompt
        assert "任务第 2 版" in prompt and old_run["id"] not in prompt
        assert context["runId"] == new_run["id"] and context["revision"] == 2
        assert launches[0]["executor"] == executor
        assert launches[0]["sessionId"] == original["sessionId"]
        assert not {"permission", "directory", "workspaceId", "projectId"} & launches[0].keys()
        retained = await store.call(
            lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],))
        )
        assert json.loads(retained["target_json"])["workspace"] == original["workspace"]
        continued = await store.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE id=?", (new_run["id"],))
        )
        assert continued["session_id"] == original["sessionId"]
        with pytest.raises(DomainError, match="ACTIVE_TASK_CONTEXT_REQUIRED"):
            await runtime.professional_capabilities.call(
                "cli_continuation-cwd", request(old_context), "local"
            )
        result = await runtime.professional_capabilities.call(
            "cli_continuation-cwd", request(context), "local"
        )
        assert result["state"] == "succeeded"
        assert result["result"]["stdout"].strip() == original["workdir"]
    finally:
        await runtime.close()
