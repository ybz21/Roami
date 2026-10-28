"""Enabled connections recover without replaying calls or changing tool permissions."""

import asyncio
import json
import os
import signal

import httpx
import pytest
from mcp import ClientSession
from test_mcp_connections import named, spec, wire
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.server.http import create_app
from roami_agent.tools import mcp
from roami_agent.tools.registry import Tools


async def eventually(predicate):
    async with asyncio.timeout(8):
        while not predicate():
            await asyncio.sleep(0.01)


async def test_idle_process_loss_recovers_and_preserves_disabled_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURE_MCP_TOKEN", "fixture-token")
    monkeypatch.setattr(mcp, "HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(mcp, "HEALTH_TIMEOUT_SECONDS", 0.1)
    registry = Tools()
    pool = mcp.MCPConnections(registry, {"docs": spec(tmp_path)})
    try:
        await pool.discover({"server": "docs"}, {})
        connection = pool.connections["docs"]
        echo = named(registry, "echo")
        registry.disabled_tools.add(echo)
        old_pid = int((tmp_path / "pid").read_text())
        os.kill(old_pid, signal.SIGKILL)
        await eventually(lambda: connection.failures > 0)
        assert not connection.names
        await eventually(lambda: connection.session is not None)
        assert int((tmp_path / "pid").read_text()) != old_pid
        assert named(registry, "echo") == echo
        with pytest.raises(DomainError, match="TOOL_DISABLED"):
            await registry.invoke(wire(echo), "worker", {})
        registry.disabled_tools.remove(echo)
        result = await registry.invoke(wire(echo, "恢复可用"), "main", {})
        assert result["structuredContent"]["text"] == "恢复可用"
        assert not (tmp_path / "called-slow").exists()
    finally:
        await pool.close()
    assert connection.monitor.done() and connection.task.done()


async def test_heartbeat_timeout_recovers_without_any_user_request(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURE_MCP_TOKEN", "fixture-token")
    monkeypatch.setattr(mcp, "HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(mcp, "HEALTH_TIMEOUT_SECONDS", 0.05)
    original = ClientSession.send_ping
    pings = []

    async def ping(session):
        pings.append(session)
        if len(pings) == 1:
            await asyncio.sleep(60)
        return await original(session)

    monkeypatch.setattr(ClientSession, "send_ping", ping)
    pool = mcp.MCPConnections(Tools(), {"docs": spec(tmp_path)})
    try:
        await pool.discover({"server": "docs"}, {})
        first_session = pool.connections["docs"].session
        await eventually(lambda: len(pings) >= 2)
        assert pool.connections["docs"].session is not first_session
    finally:
        await pool.close()


async def test_enabled_metadata_survives_restart_and_keeps_live_identity(store, tmp_path):
    runtime = Runtime(store, ConversationModel())
    config = spec(tmp_path)
    config.pop("env_env")
    imports = runtime.capability_imports
    await imports.save("local", "mcp", {"name": "exa", "config": config})
    try:
        await imports.connect_mcp("local", "exa")
        connection = runtime.mcp.connections["exa"]
        session = connection.session
        tools = list(connection.names)
        echo = named(runtime.tools, "echo")
        await runtime.capability_settings.save(
            "local", {"kind": "tools", "name": echo, "enabled": False}
        )
        updated = {
            **imports.saved["mcp"]["exa"],
            "displayName": "网页搜索",
            "description": "搜索和读取网页",
        }
        view = await imports.save("local", "mcp", updated, "exa")
        assert connection.session is session
        assert list(connection.names) == tools
        assert view["mcp"][0]["displayName"] == "网页搜索"
        assert "搜索和读取网页" in runtime.tools.registry[echo].description
        assert "网页搜索" in runtime.tools.registry["mcp_discover"].description
        for query in ("网页", "网页搜索", "搜索和读取网页"):
            matches = runtime.tools.directory.list(query, "mcp", 20, "worker")
            assert any(item["name"].startswith("mcp_exa_") for item in matches["items"])
        assert json.loads(imports.path.read_text())["mcp"]["exa"]["enabled"] is True
    finally:
        await runtime.mcp.close()
    recreated = Runtime(store, ConversationModel())
    await recreated.start()
    try:
        recovered = recreated.mcp.connections["exa"]
        await eventually(lambda: recovered.session is not None)
        assert recovered.display_name == "网页搜索"
        assert set(recovered.names) == set(tools)
        with pytest.raises(DomainError, match="TOOL_DISABLED"):
            await recreated.tools.invoke(wire(echo), "worker", {})
        await recreated.capability_settings.save(
            "local", {"kind": "tools", "name": echo, "enabled": True}
        )
        assert (await recreated.tools.invoke(wire(echo), "worker", {}))["content"] == ["ok"]
        stale = recreated.tools.registry[echo]
        await recreated.capability_imports.save("local", "mcp", None, "exa", remove=True)
        assert recovered.monitor.done() and recovered.task.done()
        assert "mcp_discover" not in recreated.tools.registry
        with pytest.raises(DomainError, match="TOOL_UNAVAILABLE"):
            await stale.handler({"text": "stale"}, {})
    finally:
        await recreated.close()


async def test_new_chinese_name_http_roundtrip_and_failed_save_preserves_metadata(
    store, monkeypatch
):
    runtime = Runtime(store, ConversationModel())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "local"},
    ) as client:
        payload = {
            "displayName": "资料检索",
            "description": "查询团队资料",
            "config": {"command": "fixture"},
        }
        response = await client.post("/v1/capability-imports/mcp", json=payload)
        assert response.status_code == 200
        item = response.json()["data"]["mcp"][0]
        name = item["name"]
        assert name.startswith("server-") and item["displayName"] == "资料检索"
        path = "/v1/capability-imports/mcp/" + name
        updated = {**payload, "name": name, "displayName": "网页检索"}
        assert (await client.put(path, json=updated)).status_code == 200
        before = runtime.capability_imports.path.read_bytes()

        def fail(*args):
            raise OSError("disk unavailable")

        monkeypatch.setattr(os, "replace", fail)
        with pytest.raises(OSError):
            await client.put(path, json={**updated, "displayName": "不应保存"})
        assert runtime.capability_imports.path.read_bytes() == before
        assert runtime.mcp.connections[name].display_name == "网页检索"
        assert (
            await client.put(path, json={**updated, "displayName": "x" * 81})
        ).status_code == 400
        assert (
            await client.put(path, json=updated, headers={"X-Roami-Owner": "foreign"})
        ).status_code == 403


async def test_failed_connect_persists_intent_and_does_not_block_other_servers(
    store, tmp_path, monkeypatch
):
    runtime = Runtime(store, ConversationModel())
    config = spec(tmp_path)
    config.pop("env_env")
    imports = runtime.capability_imports
    await imports.save(
        "local", "mcp", {"name": "unavailable", "config": {"command": "/missing/mcp-server"}}
    )
    await imports.save("local", "mcp", {"name": "healthy", "config": config})
    try:
        with pytest.raises(DomainError, match="MCP_UNAVAILABLE"):
            await imports.connect_mcp("local", "unavailable")
        assert imports.saved["mcp"]["unavailable"]["enabled"]
        assert runtime.capability_settings.view("local")["mcp"][1]["state"] == "reconnecting"
        await imports.connect_mcp("local", "healthy")
        assert runtime.mcp.connections["healthy"].session
        await imports.save("local", "mcp", None, "unavailable", remove=True)
        assert runtime.mcp.connections["healthy"].session
    finally:
        await runtime.mcp.close()


async def test_recovery_never_replays_a_dispatched_write(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURE_MCP_TOKEN", "fixture-token")
    registry = Tools()
    pool = mcp.MCPConnections(registry, {"docs": spec(tmp_path)})
    try:
        await pool.discover({"server": "docs"}, {})
        connection = pool.connections["docs"]
        connection.config["timeout_seconds"] = 0.2
        with pytest.raises(DomainError, match="MCP_OUTCOME_UNKNOWN"):
            await registry.invoke(wire(named(registry, "slow")), "worker", {})
        connection.config["timeout_seconds"] = 5
        pid = (tmp_path / "called-slow").read_text()
        await eventually(lambda: connection.session is not None)
        assert (tmp_path / "called-slow").read_text() == pid
        assert (tmp_path / "pid").read_text() != pid
        assert (await registry.invoke(wire(named(registry, "echo")), "worker", {}))["content"] == [
            "ok"
        ]
    finally:
        await pool.close()


async def test_streamable_http_expired_session_reconnects_and_calls_agent_tool(monkeypatch):
    import socket

    import uvicorn
    from mcp.server.fastmcp import FastMCP
    from starlette.responses import Response

    fixture = FastMCP("expiring-fixture")

    @fixture.tool()
    def echo(text: str) -> str:
        return text

    app = fixture.streamable_http_app()
    initialized, expired = [], []

    async def expiring(scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await app(scope, receive, send)
        packets, body = [], b""
        while True:
            packet = await receive()
            packets.append(packet)
            body += packet.get("body", b"")
            if not packet.get("more_body"):
                break
        method = json.loads(body).get("method")
        session_id = dict(scope["headers"]).get(b"mcp-session-id")
        if method == "initialize":
            initialized.append(session_id)
        if method == "ping" and not expired:
            expired.append(session_id)
        if session_id and session_id in expired:
            return await Response(status_code=404)(scope, receive, send)

        async def replay():
            return packets.pop(0) if packets else await receive()

        return await app(scope, replay, send)

    monkeypatch.setattr(mcp, "HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(mcp, "HEALTH_TIMEOUT_SECONDS", 1)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(expiring, log_level="error"))
        serving = asyncio.create_task(server.serve(sockets=[sock]))
        registry = Tools()
        pool = mcp.MCPConnections(
            registry,
            {
                "http": {
                    "transport": "streamable_http",
                    "url": f"http://127.0.0.1:{sock.getsockname()[1]}/mcp",
                }
            },
        )
        try:
            await eventually(lambda: server.started)
            await pool.discover({"server": "http"}, {})
            alias = named(registry, "echo")
            await eventually(
                lambda: len(initialized) >= 2 and pool.connections["http"].session is not None
            )
            assert expired[0]
            assert named(registry, "echo") == alias
            assert (await registry.invoke(wire(alias, "session recovered"), "worker", {}))[
                "content"
            ] == ["session recovered"]
        finally:
            await pool.close()
            server.should_exit = True
            await serving


async def test_pool_close_finishes_when_protocol_ping_consumes_cancellation(tmp_path, monkeypatch):
    from roami_agent.tools import mcp

    monkeypatch.setenv("FIXTURE_MCP_TOKEN", "fixture-token")
    monkeypatch.setattr(mcp, "HEARTBEAT_SECONDS", 0.05)
    pool = mcp.MCPConnections(Tools(), {"docs": spec(tmp_path)})
    entered = asyncio.Event()
    try:
        await pool.discover({"server": "docs"}, {})
        connection = pool.connections["docs"]

        async def interrupted_ping():
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return

        session = connection.session
        original_ping = session.send_ping
        monkeypatch.setattr(session, "send_ping", interrupted_ping)
        await asyncio.wait_for(entered.wait(), timeout=2)
        closing = asyncio.create_task(pool.close())
        try:
            done, _ = await asyncio.wait({closing}, timeout=2)
            assert closing in done
            assert connection.task.done()
            assert connection.session is None
        finally:
            monkeypatch.setattr(session, "send_ping", original_ping)
            if not connection.task.done():
                os.kill(int((tmp_path / "pid").read_text()), signal.SIGTERM)
                connection.task.cancel()
            await asyncio.wait_for(closing, timeout=3)
    finally:
        await pool.close()
