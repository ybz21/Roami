import asyncio
import json
import os
import socket
import sys
from pathlib import Path

import pytest
import uvicorn
from mcp import ClientSession
from mcp.server.fastmcp import FastMCP
from starlette.responses import Response

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import rows
from roami_agent.tools.mcp import MCPConnections, validate_servers
from roami_agent.tools.registry import Tools


def spec(tmp_path):
    (tmp_path / "state.json").write_text("{}")
    return {
        "command": sys.executable,
        "args": [str(Path(__file__).with_name("mcp_fixture.py")), str(tmp_path)],
        "env_env": {"MCP_AUTH_TOKEN": "FIXTURE_MCP_TOKEN"},
        "read_only": ["echo"],
    }


def wire(name, text="hello"):
    return {"id": "call", "function": {"name": name, "arguments": json.dumps({"text": text})}}


def named(registry, remote):
    return next(name for name in registry.registry if "_" + remote + "_" in name)


async def test_stdio_discovery_namespaces_scopes_credentials_and_catalog_change(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("FIXTURE_MCP_TOKEN", "fixture-token")
    monkeypatch.setenv("ROAMI_AGENT_API_KEY", "must-not-inherit")
    registry = Tools()
    config = spec(tmp_path)
    pool = MCPConnections(registry, {"docs": config, "other": config})
    try:
        assert registry.catalog("main") == []
        assert len(registry.catalog("worker")) == 1
        first = await pool.discover({"server": "docs"}, {})
        echo = named(registry, "echo")
        assert registry.registry[echo].effect == "read"
        assert registry.registry[named(registry, "slow")].effect == "write"
        with pytest.raises(DomainError, match="TOOL_UNAVAILABLE"):
            await registry.invoke(wire(echo), "main", {})
        result = await registry.invoke(wire(echo, "中文"), "worker", {})
        assert result["structuredContent"] == {
            "text": "中文",
            "credentialConfigured": True,
            "modelKeyInherited": False,
        }
        assert (await pool.discover({"server": "docs"}, {}))["catalogVersion"] == first[
            "catalogVersion"
        ]
        await pool.discover({"server": "other"}, {})
        assert len([name for name in registry.registry if "_echo_" in name]) == 2
        stale = registry.registry[echo]
        (tmp_path / "state.json").write_text('{"changed":true}')
        with pytest.raises(DomainError, match="TOOL_UNAVAILABLE"):
            await stale.handler({"text": "hello"}, {})
        assert echo not in registry.registry
        assert pool.connections["docs"].version != first["catalogVersion"]
        assert named(registry, "echo") != echo
    finally:
        await pool.close()
    assert list(registry.registry) == ["mcp_discover"]


async def test_stdio_timeout_cancels_process_and_does_not_replay_write(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURE_MCP_TOKEN", "fixture-token")
    registry = Tools()
    pool = MCPConnections(registry, {"docs": spec(tmp_path)})
    try:
        await pool.discover({"server": "docs"}, {})
        pool.connections["docs"].config["timeout_seconds"] = 1
        with pytest.raises(DomainError, match="MCP_OUTCOME_UNKNOWN"):
            await registry.invoke(wire(named(registry, "slow")), "worker", {})
        pid = int((tmp_path / "called-slow").read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert not any(name.startswith("mcp_docs_") for name in registry.registry)
        with pytest.raises(DomainError, match="MCP_RECONNECT_BACKOFF"):
            await pool.discover({"server": "docs"}, {})
        pool.connections["docs"].retry_after = 0
        await pool.discover({"server": "docs"}, {})
        assert int((tmp_path / "pid").read_text()) != pid
        assert int((tmp_path / "called-slow").read_text()) == pid
    finally:
        await pool.close()


async def test_stdio_caller_cancel_cleans_up_and_invalidates_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURE_MCP_TOKEN", "fixture-token")
    registry = Tools()
    sent = []
    original = ClientSession.send_notification

    async def record(session, notification, *args, **kwargs):
        if notification.root.method == "notifications/cancelled":
            sent.append(notification.root.params.requestId)
        return await original(session, notification, *args, **kwargs)

    monkeypatch.setattr(ClientSession, "send_notification", record)
    pool = MCPConnections(registry, {"docs": spec(tmp_path)})
    try:
        await pool.discover({"server": "docs"}, {})
        running = asyncio.create_task(registry.invoke(wire(named(registry, "slow")), "worker", {}))
        async with asyncio.timeout(5):
            while not (tmp_path / "called-slow").exists():
                await asyncio.sleep(0.01)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert len(sent) == 1 and isinstance(sent[0], int)
        with pytest.raises(ProcessLookupError):
            os.kill(int((tmp_path / "pid").read_text()), 0)
    finally:
        await pool.close()


async def test_stdio_change_notification_invalidates_the_old_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURE_MCP_TOKEN", "fixture-token")
    registry = Tools()
    pool = MCPConnections(registry, {"docs": spec(tmp_path)})
    try:
        await pool.discover({"server": "docs"}, {})
        await registry.invoke(wire(named(registry, "changed")), "worker", {})
        async with asyncio.timeout(5):
            while pool.connections["docs"].names:
                await asyncio.sleep(0.01)
        refreshed = await pool.discover({"server": "docs"}, {})
        assert refreshed["tools"]
    finally:
        await pool.close()


@pytest.mark.parametrize("remote", ["failure", "large"])
async def test_stdio_unusable_result_is_not_a_success_or_secret_leak(tmp_path, monkeypatch, remote):
    monkeypatch.setenv("FIXTURE_MCP_TOKEN", "fixture-token")
    registry = Tools()
    pool = MCPConnections(registry, {"docs": spec(tmp_path)})
    try:
        await pool.discover({"server": "docs"}, {})
        with pytest.raises(DomainError, match="^MCP_OUTCOME_UNKNOWN$"):
            await registry.invoke(wire(named(registry, remote)), "worker", {})
    finally:
        await pool.close()


async def test_streamable_http_initialization_authentication_and_call(monkeypatch):
    fixture = FastMCP("http-fixture")

    @fixture.tool()
    def echo(text: str) -> str:
        return text

    app = fixture.streamable_http_app()

    async def authenticated(scope, receive, send):
        if (
            scope["type"] == "http"
            and dict(scope["headers"]).get(b"authorization") != b"Bearer fixture-token"
        ):
            await Response(status_code=401)(scope, receive, send)
        else:
            await app(scope, receive, send)

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        config = {
            "transport": "streamable_http",
            "url": f"http://127.0.0.1:{sock.getsockname()[1]}/mcp",
            "key_env": "FIXTURE_MCP_TOKEN",
            "read_only": ["echo"],
        }
        server = uvicorn.Server(uvicorn.Config(authenticated, log_level="error"))
        serving = asyncio.create_task(server.serve(sockets=[sock]))
        registry = Tools()
        pool = MCPConnections(registry, {"http": config})
        monkeypatch.setenv("FIXTURE_MCP_TOKEN", "fixture-token")
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    await asyncio.sleep(0.01)
            await pool.discover({"server": "http"}, {})
            result = await registry.invoke(wire(named(registry, "echo"), "real HTTP"), "worker", {})
            assert result["content"] == ["real HTTP"]
        finally:
            await pool.close()
            server.should_exit = True
            await serving


@pytest.mark.parametrize(
    "config",
    [
        {"command": ""},
        {"command": "a", "args": "shell string"},
        {"transport": "streamable_http", "url": "http://example.com/mcp"},
        {"transport": "streamable_http", "url": "https://user:secret@example.com/mcp"},
        {"transport": "streamable_http", "url": "https://example.com/mcp?token=secret"},
        {"command": "a", "timeout_seconds": 0},
        {"command": "a", "env_env": {"KEY": 1}},
    ],
)
def test_invalid_configuration_fails_before_starting_a_process(config):
    with pytest.raises(DomainError, match="INVALID_MCP_CONFIG"):
        validate_servers({"test": config})


@pytest.mark.parametrize(
    "remote, expected",
    [
        ("echo", "succeeded"),
        ("image", "waiting_user"),
        ("large", "waiting_user"),
        ("failure", "interrupted"),
    ],
)
async def test_worker_discovers_calls_and_records_mcp_outcomes(
    store, tmp_path, monkeypatch, remote, expected
):
    from test_runtime import until

    monkeypatch.setenv("FIXTURE_MCP_TOKEN", "fixture-token")

    class MCPModel:
        model = "mcp-fixture-model"
        calls = 0

        async def stream(self, messages, tools):
            names = [tool["function"]["name"] for tool in tools]
            if "mcp_discover" not in names:
                yield ModelEvent("text", "Task result received")
                return
            self.calls += 1
            if messages[-1]["role"] == "tool" and "structuredContent" in messages[-1]["content"]:
                yield ModelEvent("text", "Verified read-only MCP result")
                return
            alias = next((name for name in names if "_" + remote + "_" in name), None)
            name, args = (
                (alias, {"text": "hello"}) if alias else ("mcp_discover", {"server": "docs"})
            )
            yield ModelEvent(
                "tool",
                {
                    "id": "mcp-" + str(self.calls),
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                },
            )

    model = MCPModel()
    runtime = Runtime(store, model, settings=Settings(mcp_servers={"docs": spec(tmp_path)}))
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", conversation["id"], "MCP task", key="mcp-task", record_intent=True
        )
        runtime.wakeup.set()
        await until(
            store,
            lambda db: (
                db.execute("SELECT state FROM tasks WHERE id=?", (task["id"],)).fetchone()[0]
                == expected
            ),
            timeout=10,
        )
        calls = await store.call(
            lambda db: rows(db, "SELECT tool_name,state FROM tool_calls ORDER BY created_ms")
        )
        if remote in {"image", "large"}:
            artifacts = await runtime.artifacts.list("alice", task_id=task["id"])
            assert len(artifacts) == 1 and artifacts[0]["messageId"]
            reference, body = await runtime.artifacts.read("alice", artifacts[0]["id"])
            assert body == (b"fixture-image" if remote == "image" else b"x" * 65_000)
            assert reference["metadata"]["tool"] == remote
            tool_messages = await store.call(
                lambda db: rows(db, "SELECT content_json FROM messages WHERE role='tool'")
            )
            assert any(reference["id"] in message["content_json"] for message in tool_messages)
            assert all(len(message["content_json"]) < 16_000 for message in tool_messages)
            with pytest.raises(DomainError, match="ARTIFACT_NOT_FOUND"):
                await runtime.artifacts.read("bob", reference["id"])
        assert len(calls) == 2
        assert calls[-1]["state"] == ("succeeded" if expected != "interrupted" else "unknown")
        assert model.calls == (3 if expected != "interrupted" else 2)
        manifests = await store.call(
            lambda db: rows(
                db,
                "SELECT parts_json FROM prompt_manifests p JOIN turns t ON t.id=p.turn_id JOIN task_attempts a ON a.native_branch_id=t.branch_id WHERE a.task_id=? ORDER BY p.attempt_no",
                (task["id"],),
            )
        )
        hashes = [json.loads(manifest["parts_json"])["catalogHash"] for manifest in manifests]
        assert len(set(hashes)) == 2
        progress = await store.call(
            lambda db: rows(db, "SELECT payload_json FROM events WHERE kind='tool.progress'")
        )
        assert progress
        assert all("sensitive progress detail" not in entry["payload_json"] for entry in progress)
    finally:
        await runtime.close()
