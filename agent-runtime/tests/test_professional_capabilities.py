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
    assert "capability read NAME --context" in launches[0]["prompt"]
    assert "--call UNIQUE_REQUEST_ID" in launches[0]["prompt"]
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
