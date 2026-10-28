"""A separate MCP owner keeps connections when Agent clients leave and return."""

import asyncio
import json
import os
import signal
import tempfile
import uuid
from pathlib import Path

import httpx
import pytest
import uvicorn
from test_mcp_connections import named, spec, wire
from test_mcp_maintenance import eventually

from roami_agent.protocol.errors import DomainError
from roami_agent.server.mcp_daemon import MCPDaemon, create_app
from roami_agent.tools.mcp import MCPConnections
from roami_agent.tools.mcp_broker import MCPBroker, config_fingerprint
from roami_agent.tools.registry import Tools


@pytest.fixture
async def daemon(tmp_path, monkeypatch):
    from roami_agent.tools import mcp

    monkeypatch.setattr(mcp, "HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setenv("FIXTURE_MCP_TOKEN", "fixture-token")
    root = tmp_path / "node"
    (root / "agents").mkdir(parents=True, mode=0o700)
    config = spec(tmp_path)
    config["transport"] = "stdio"
    managed = {
        "skills": {},
        "cli": {},
        "mcp": {"docs": {"name": "docs", "config": config, "enabled": True}},
    }
    imports = root / "agents/capability-imports.json"
    imports.write_text(json.dumps(managed))
    imports.chmod(0o600)
    (root / "agent.toml").write_text("")
    owner = MCPDaemon(root, root / "agent.toml")
    with tempfile.TemporaryDirectory(prefix="rmcp-") as short:
        path = Path(short) / "m.sock"
        server = uvicorn.Server(
            uvicorn.Config(
                create_app(owner), uds=str(path), log_level="error", timeout_graceful_shutdown=1
            )
        )
        serving = asyncio.create_task(server.serve())
        try:
            await eventually(lambda: server.started)
            path.chmod(0o600)
            await eventually(lambda: owner.pool.connections["docs"].session is not None)
            yield owner, path, config, imports
        finally:
            server.should_exit = True
            try:
                await asyncio.wait_for(asyncio.shield(serving), timeout=8)
            except TimeoutError:
                for task in asyncio.all_tasks():
                    task.print_stack()
                for connection in owner.pool.connections.values():
                    if connection.task:
                        connection.task.cancel()
                await asyncio.wait_for(serving, timeout=5)
                raise


async def client(path, config):
    registry = Tools()
    pool = MCPConnections(registry, {"docs": config}, broker=MCPBroker(path))
    pool.connections["docs"].enabled = True
    pool.start()
    await pool.refresh()
    return pool, registry


async def test_client_close_and_new_agent_preserve_upstream_connection(daemon, tmp_path):
    owner, path, config, _ = daemon
    first, registry = await client(path, config)
    upstream = owner.pool.connections["docs"].session
    pid = int((tmp_path / "pid").read_text())
    alias = named(registry, "echo")
    progress = []

    async def report(value, total, message):
        progress.append((value, total))

    try:
        result = await registry.invoke(wire(alias, "中文"), "main", {"progress": report})
        assert result["structuredContent"]["text"] == "中文"
        assert progress == [(1, 2)]
    finally:
        await first.close()
    assert owner.pool.connections["docs"].session is upstream
    assert int((tmp_path / "pid").read_text()) == pid
    second, registry = await client(path, config)
    try:
        assert named(registry, "echo") == alias
        assert (await registry.invoke(wire(alias), "worker", {}))["content"] == ["ok"]
        assert owner.pool.connections["docs"].session is upstream
    finally:
        await second.close()


async def test_daemon_reconnects_while_all_agent_clients_are_stopped(daemon, tmp_path, monkeypatch):
    from roami_agent.tools import mcp

    monkeypatch.setattr(mcp, "HEARTBEAT_SECONDS", 0.05)
    owner, path, config, _ = daemon
    first, _ = await client(path, config)
    await first.close()
    pid = int((tmp_path / "pid").read_text())
    os.kill(pid, signal.SIGKILL)
    await eventually(lambda: owner.pool.connections["docs"].failures > 0)
    await eventually(lambda: owner.pool.connections["docs"].session is not None)
    assert int((tmp_path / "pid").read_text()) != pid
    second, registry = await client(path, config)
    try:
        assert (await registry.invoke(wire(named(registry, "echo")), "worker", {}))["content"] == [
            "ok"
        ]
    finally:
        await second.close()


async def test_shutdown_does_not_cancel_an_admitted_remote_call(daemon, tmp_path):
    owner, path, config, _ = daemon
    pool, registry = await client(path, config)
    upstream = owner.pool.connections["docs"].session
    running = asyncio.create_task(registry.invoke(wire(named(registry, "slow")), "worker", {}))
    await eventually(lambda: (tmp_path / "called-slow").exists())
    pool.shutting_down = True
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    await pool.close()
    assert owner.calls
    assert owner.pool.connections["docs"].session is upstream
    assert owner.pool.connections["docs"].current is not None


async def test_timeout_before_response_headers_preserves_unknown_write_outcome(
    daemon, tmp_path, monkeypatch
):
    owner, path, config, imports = daemon
    config["timeout_seconds"] = 2
    saved = json.loads(imports.read_text())
    saved["mcp"]["docs"]["config"] = config
    imports.write_text(json.dumps(saved))
    await owner.reconcile()
    await eventually(lambda: owner.pool.connections["docs"].session is not None)
    accept = owner.call
    release_headers, finished = asyncio.Event(), asyncio.Event()

    async def delayed_headers(body):
        response = await accept(body)
        try:
            await release_headers.wait()
        finally:
            finished.set()
        return response

    monkeypatch.setattr(owner, "call", delayed_headers)
    pool, registry = await client(path, config)
    try:
        with pytest.raises(DomainError, match="MCP_OUTCOME_UNKNOWN"):
            await registry.invoke(wire(named(registry, "changed")), "worker", {})
        assert (tmp_path / "called-changed").exists()
        assert json.loads((tmp_path / "state.json").read_text())["changed"] is True
        assert len(owner.seen) == 1
    finally:
        release_headers.set()
        await eventually(finished.is_set)
        await pool.close()


async def test_explicit_cancellation_still_stops_the_remote_call(daemon, tmp_path):
    owner, path, config, _ = daemon
    pool, registry = await client(path, config)
    try:
        running = asyncio.create_task(registry.invoke(wire(named(registry, "slow")), "worker", {}))
        await eventually(lambda: (tmp_path / "called-slow").exists())
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        await eventually(lambda: not owner.calls)
        assert owner.pool.connections["docs"].current is None
    finally:
        await pool.close()


async def test_duplicate_call_id_and_disabled_policy_do_not_execute_twice(daemon, tmp_path):
    owner, path, config, imports = daemon
    alias = named(owner.registry, "echo")
    payload = {
        "callId": uuid.uuid4().hex,
        "server": "docs",
        "alias": alias,
        "fingerprint": config_fingerprint(config),
        "arguments": {"text": "once"},
    }
    async with httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(uds=str(path)), base_url="http://mcp"
    ) as http:
        response = await http.post("/v1/calls", json=payload)
        assert response.status_code == 200 and '"kind":"result"' in response.text
        response = await http.post("/v1/calls", json=payload)
        assert response.json()["error"]["code"] == "MCP_OUTCOME_UNKNOWN"
        policy = imports.parent / "capability-settings.json"
        policy.write_text(json.dumps({"tools": [alias], "skills": []}))
        policy.chmod(0o600)
        response = await http.post("/v1/calls", json={**payload, "callId": uuid.uuid4().hex})
        assert response.json()["error"]["code"] == "TOOL_DISABLED"


async def test_removal_and_new_server_configuration_are_observed_without_restart(daemon):
    owner, path, config, imports = daemon
    pool, registry = await client(path, config)
    connection = owner.pool.connections["docs"]
    value = json.loads(imports.read_text())
    value["mcp"] = {}
    imports.write_text(json.dumps(value))
    try:
        await pool.refresh(sync=True)
        assert "docs" not in owner.pool.connections
        assert connection.task.done() and connection.monitor.done()
        assert not any(name.startswith("mcp_docs_") for name in registry.registry)
        value["mcp"]["docs"] = {"name": "docs", "config": config, "enabled": True}
        imports.write_text(json.dumps(value))
        await pool.refresh(sync=True)
        await eventually(lambda: owner.pool.connections["docs"].session is not None)
        await pool.refresh()
        assert named(registry, "echo")
    finally:
        await pool.close()


async def test_missing_daemon_never_falls_back_to_spawning_upstream(daemon, tmp_path):
    owner, path, config, _ = daemon
    pool, registry = await client(path, config)
    try:
        pool.broker.socket_path = path.with_name("missing.sock")
        await pool.refresh()
        assert pool.state(pool.connections["docs"]) == "reconnecting"
        assert pool.connections["docs"].task is None
        assert not any(name.startswith("mcp_docs_") for name in registry.registry)
        with pytest.raises(DomainError, match="MCP_DAEMON_UNAVAILABLE"):
            await pool.discover({"server": "docs"}, {})
        assert owner.pool.connections["docs"].session
    finally:
        await pool.close()


def test_node_descriptor_is_private_and_enables_broker_without_environment(tmp_path, monkeypatch):
    from roami_agent.tools.mcp_broker import node_socket

    monkeypatch.delenv("ROAMI_MCP_SOCKET", raising=False)
    (tmp_path / "agents").mkdir(mode=0o700)
    path = tmp_path / "agents/mcp-daemon.json"
    assert node_socket(tmp_path) is None
    path.write_text(json.dumps({"version": 1, "socket": "/private/mcp.sock"}))
    path.chmod(0o600)
    assert node_socket(tmp_path) == Path("/private/mcp.sock")
    path.chmod(0o644)
    with pytest.raises(DomainError, match="MCP_CONFIGURATION_INVALID"):
        node_socket(tmp_path)


async def test_real_agent_process_can_stop_and_reconnect_to_same_upstream(daemon, tmp_path):
    import sys

    owner, path, _config, _ = daemon
    upstream = owner.pool.connections["docs"].session
    pid = int((tmp_path / "pid").read_text())
    script = tmp_path / "agent_client.py"
    script.write_text("""import asyncio,json,sys
from pathlib import Path
from test_runtime import ConversationModel
from roami_agent.app import Runtime
from roami_agent.storage.database import Database
from roami_agent.server.configuration import Settings
async def main():
 root=Path(sys.argv[1]);db=Database(root/'database/agents/runtime.db',root,managed=False);await db.open()
 runtime=Runtime(db,ConversationModel(),settings=Settings(workers=0))
 await runtime.start()
 try:
  assert runtime.mcp.broker is not None
  echo=next(name for name in runtime.tools.registry if '_echo_' in name)
  call={'function':{'name':echo,'arguments':json.dumps({'text':'separate process'})}}
  result=await runtime.tools.invoke(call,'worker',{})
  assert result['structuredContent']['text']=='separate process'
  print(json.dumps({'ready':True,'alias':echo}),flush=True)
  await asyncio.to_thread(sys.stdin.readline)
 finally:
  await runtime.close();await db.close()
asyncio.run(main())
""")
    descriptor = owner.root / "agents/mcp-daemon.json"
    descriptor.write_text(json.dumps({"version": 1, "socket": str(path)}))
    descriptor.chmod(0o600)
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parent)}
    env.pop("ROAMI_MCP_SOCKET", None)
    aliases = []
    for index in range(2):
        with (tmp_path / f"agent-{index}.log").open("w") as log:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(script),
                str(owner.root),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=log,
            )
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=10)
                assert line, (tmp_path / f"agent-{index}.log").read_text()
                aliases.append(json.loads(line)["alias"])
                process.stdin.close()
                assert await asyncio.wait_for(process.wait(), timeout=10) == 0
                assert owner.pool.connections["docs"].session is upstream
                assert int((tmp_path / "pid").read_text()) == pid
            finally:
                if process.returncode is None:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=10)
    assert aliases[0] == aliases[1]


async def test_duplicate_daemon_cannot_unlink_a_live_socket(daemon, tmp_path):
    import sys

    owner, path, _, _ = daemon
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "roami_agent.server.mcp_daemon",
        "--data-root",
        str(owner.root),
        "--config",
        str(owner.config),
        "--socket",
        str(path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, error = await asyncio.wait_for(process.communicate(), timeout=5)
    assert process.returncode != 0
    assert b"MCP_SOCKET_ALREADY_LISTENING" in error
    assert path.exists()
    async with httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(uds=str(path)), base_url="http://mcp"
    ) as http:
        assert (await http.get("/v1/state")).status_code == 200


async def test_malformed_configuration_fails_closed_and_recovers(daemon):
    owner, path, config, imports = daemon
    pool, registry = await client(path, config)
    session = owner.pool.connections["docs"].session
    saved = imports.read_bytes()
    try:
        imports.write_text('{"mcp":[]}')
        await pool.refresh(sync=True)
        assert owner.invalid and owner.pool.connections["docs"].session is session
        assert not any(name.startswith("mcp_docs_") for name in registry.registry)
        imports.write_bytes(saved)
        await pool.refresh(sync=True)
        assert not owner.invalid
        assert owner.pool.connections["docs"].session is session
        assert named(registry, "echo")
    finally:
        await pool.close()


async def test_broker_rejects_a_socket_belonging_to_a_different_node(daemon, tmp_path):
    owner, path, config, _ = daemon
    registry = Tools()
    pool = MCPConnections(
        registry, {"docs": config}, broker=MCPBroker(path, data_root=tmp_path / "different-node")
    )
    try:
        with pytest.raises(DomainError, match="MCP_DAEMON_INSTANCE_MISMATCH"):
            await pool.discover({"server": "docs"}, {})
        assert not any(name.startswith("mcp_docs_") for name in registry.registry)
        assert owner.pool.connections["docs"].session
    finally:
        await pool.close()


@pytest.mark.parametrize("remote,expected", [("image", b"fixture-image"), ("large", b"x" * 65000)])
async def test_broker_keeps_binary_and_large_results_in_the_agent_artifact_store(
    daemon, store, remote, expected
):
    from roami_agent.storage.artifact_store import ArtifactStore

    _, path, config, _ = daemon
    artifacts = ArtifactStore(store)
    registry = Tools()
    pool = MCPConnections(registry, {"docs": config}, artifacts, broker=MCPBroker(path))
    try:
        await pool.refresh()
        result = await registry.invoke(wire(named(registry, remote)), "worker", {"owner": "alice"})
        assert result["outputExternalized"] is True
        reference = result["artifactRefs"][0]
        _, body = await artifacts.read("alice", reference["id"])
        assert body == expected
        with pytest.raises(DomainError, match="ARTIFACT_NOT_FOUND"):
            await artifacts.read("bob", reference["id"])
    finally:
        await pool.close()
        await artifacts.close()
