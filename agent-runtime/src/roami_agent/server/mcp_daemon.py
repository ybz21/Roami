"""Node-local MCP owner. Its lifetime is independent of Web and Agent clients."""

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import re
import socket
import stat
import time
import tomllib
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from mcp import types

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.server.capability_imports import CapabilityImports
from roami_agent.tools.mcp import Connection, MCPConnections, validate_servers
from roami_agent.tools.mcp_broker import config_fingerprint
from roami_agent.tools.registry import Tools


def private_json(path, default):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return default
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
        or info.st_size > 1048576
    ):
        raise DomainError("MCP_CONFIGURATION_INVALID")
    return json.loads(path.read_text())


class MCPDaemon:
    def __init__(self, data_root, config_path):
        self.root, self.config = data_root, config_path
        self.registry = Tools()
        self.pool = MCPConnections(self.registry, {})
        self.lock = asyncio.Lock()
        self.changed = asyncio.Event()
        self.revision = ""
        self.watcher = None
        self.calls = {}
        self.seen = {}
        self.desired = {}
        self.invalid = False
        self.closed = False

    def configuration(self):
        document = tomllib.loads(self.config.read_text()) if self.config.exists() else {}
        tools = document.get("tools", {})
        if not isinstance(tools, dict):
            raise DomainError("MCP_CONFIGURATION_INVALID")
        base = tools.get("mcp", {})
        validate_servers(base)
        entries = {
            name: {"name": name, "config": config, "enabled": True} for name, config in base.items()
        }
        managed = private_json(self.root / "agents/capability-imports.json", {"mcp": {}})
        if not isinstance(managed, dict) or not isinstance(managed.get("mcp"), dict):
            raise DomainError("MCP_CONFIGURATION_INVALID")
        for name, value in managed["mcp"].items():
            checked = CapabilityImports.validate("mcp", value)
            if checked["name"] != name or name in entries:
                raise DomainError("MCP_CONFIGURATION_INVALID")
            entries[name] = checked
        validate_servers({name: entry["config"] for name, entry in entries.items()})
        return entries

    async def reconcile(self):
        async with self.lock:
            try:
                entries = self.configuration()
                policy = private_json(self.root / "agents/capability-settings.json", {"tools": []})
                if (
                    not isinstance(policy, dict)
                    or not isinstance(policy.get("tools"), list)
                    or not all(isinstance(name, str) for name in policy["tools"])
                ):
                    raise DomainError("MCP_CONFIGURATION_INVALID")
            except (OSError, ValueError, KeyError, TypeError, DomainError):
                self.invalid = True
                self.notify()
                return
            self.invalid = False
            self.desired = entries
            self.registry.disabled_tools = set(policy["tools"])
            changed_connections = False
            for name, connection in list(self.pool.connections.items()):
                desired = entries.get(name)
                replace = not desired or desired["config"] != connection.config
                disable = desired and not desired.get("enabled", False)
                if replace or disable:
                    # Keep an admitted write alive while a client is restarting or changing config.
                    if connection.current or not connection.queue.empty():
                        continue
                    await self.pool.stop(connection)
                    self.pool._remove(connection)
                    if replace:
                        self.pool.connections.pop(name)
                        changed_connections = True
            for name, entry in entries.items():
                connection = self.pool.connections.get(name)
                if connection is None:
                    connection = Connection(name, entry["config"])
                    self.pool.connections[name] = connection
                    changed_connections = True
                metadata = (entry.get("displayName", name), entry.get("description", ""))
                if metadata != (connection.display_name, connection.description):
                    self.pool.update_metadata(connection, *metadata)
                if entry.get("enabled", False) and not connection.enabled:
                    self.pool.activate(connection)
            if changed_connections:
                self.pool.register_discovery()
            self.notify()

    def snapshot(self):
        servers = {
            name: {
                "fingerprint": config_fingerprint(c.config),
                "state": "unavailable" if self.invalid else self.pool.state(c),
                "catalogVersion": c.version,
                "connectionId": c.connection_id,
                "busy": bool(c.current or not c.queue.empty()),
            }
            for name, c in self.pool.connections.items()
        }
        revision = hashlib.sha256(encoded(servers).encode()).hexdigest()
        return {
            "revision": revision,
            "servers": servers,
            "dataRoot": str(self.root.resolve()),
            "pid": os.getpid(),
        }

    def notify(self):
        revision = self.snapshot()["revision"]
        if revision != self.revision:
            self.revision = revision
            self.changed.set()
            self.changed = asyncio.Event()

    async def watch(self):
        while not self.closed:
            await self.reconcile()
            await asyncio.sleep(1)

    async def start(self):
        await self.reconcile()
        self.watcher = asyncio.create_task(self.watch(), name="mcp-daemon-config")

    def admitted(self, name):
        if self.invalid:
            raise DomainError("MCP_CONFIGURATION_INVALID")
        desired = self.desired.get(name)
        if not desired or not desired.get("enabled", False):
            raise DomainError("TOOL_UNAVAILABLE")
        connection = self.pool.connections.get(name)
        if not connection or connection.config != desired["config"]:
            raise DomainError("MCP_BUSY")
        return connection

    def catalog(self, name):
        connection = self.admitted(name)
        return {
            "fingerprint": config_fingerprint(connection.config),
            "tools": [
                types.Tool(
                    name=remote,
                    description=connection.descriptions[alias],
                    inputSchema=self.registry.registry[alias].schema,
                ).model_dump(mode="json", by_alias=True, exclude_none=True)
                for alias, remote in connection.names.items()
            ],
        }

    async def call(self, body):
        if (
            not isinstance(body, dict)
            or set(body) != {"callId", "server", "fingerprint", "alias", "arguments"}
            or not isinstance(body["callId"], str)
            or not re.fullmatch(r"[a-f0-9]{32}", body["callId"])
            or not isinstance(body["server"], str)
            or not isinstance(body["alias"], str)
            or not isinstance(body["arguments"], dict)
        ):
            raise DomainError("INVALID_TOOL_ARGUMENTS")
        await self.reconcile()
        connection = self.admitted(body["server"])
        if (
            body["fingerprint"] != config_fingerprint(connection.config)
            or body["alias"] not in connection.names
        ):
            raise DomainError("TOOL_UNAVAILABLE")
        self.registry.validate(
            {"function": {"name": body["alias"], "arguments": encoded(body["arguments"])}}, "worker"
        )
        if "bash" in self.registry.disabled_tools:
            raise DomainError("TOOL_DISABLED")
        call_id = body["callId"]
        if call_id in self.seen:
            raise DomainError("MCP_OUTCOME_UNKNOWN")
        if len(self.calls) >= 64:
            raise DomainError("MCP_BUSY")
        self.seen = {
            key: stamp
            for key, stamp in self.seen.items()
            if key in self.calls or time.monotonic() - stamp < 3600
        }
        if len(self.seen) >= 4096:
            completed = next(key for key in self.seen if key not in self.calls)
            self.seen.pop(completed)
        self.seen[call_id] = time.monotonic()
        queue = asyncio.Queue(64)

        def publish(event):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

        async def progress(value, total, message):
            publish({"kind": "progress", "progress": value, "total": total, "message": message})

        async def execute():
            try:
                answer = await self.pool._request(
                    connection,
                    "call",
                    {"alias": body["alias"], "arguments": body["arguments"], "progress": progress},
                )
                publish(
                    {
                        "kind": "result",
                        "result": answer.model_dump(mode="json", by_alias=True, exclude_none=True),
                    }
                )
            except DomainError as error:
                publish({"kind": "error", "code": error.code})
            except (Exception, asyncio.CancelledError):  # noqa: BLE001
                publish({"kind": "error", "code": "MCP_OUTCOME_UNKNOWN"})
            finally:
                self.calls.pop(call_id, None)
                self.notify()

        self.calls[call_id] = asyncio.create_task(execute(), name="mcp-call-" + call_id)

        async def stream():
            yield encoded({"kind": "started"}) + "\n"
            while True:
                event = await queue.get()
                yield encoded(event) + "\n"
                if event["kind"] in {"result", "error"}:
                    return

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    async def close(self):
        self.closed = True
        if self.watcher:
            self.watcher.cancel()
            await asyncio.gather(self.watcher, return_exceptions=True)
        await self.pool.close()
        tasks = list(self.calls.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def create_app(daemon):
    @asynccontextmanager
    async def lifespan(app):
        await daemon.start()
        try:
            yield
        finally:
            await daemon.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def instance_boundary(request, call_next):
        expected = hashlib.sha256(str(daemon.root.resolve()).encode()).hexdigest()
        supplied = request.headers.get("X-Roami-Instance")
        if supplied and supplied != expected:
            return JSONResponse(
                {"error": {"code": "MCP_DAEMON_INSTANCE_MISMATCH"}}, status_code=409
            )
        return await call_next(request)

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return JSONResponse({"error": {"code": error.code}}, status_code=409)

    @app.get("/v1/state")
    async def state(since: str = ""):
        snapshot = daemon.snapshot()
        if since and since == snapshot["revision"]:
            changed = daemon.changed
            snapshot = daemon.snapshot()
            if since == snapshot["revision"]:
                try:
                    await asyncio.wait_for(changed.wait(), timeout=25)
                except TimeoutError:
                    pass
        return daemon.snapshot()

    @app.post("/v1/state")
    async def synchronize():
        await daemon.reconcile()
        return daemon.snapshot()

    @app.get("/v1/catalog/{name}")
    async def catalog(name: str):
        return daemon.catalog(name)

    @app.post("/v1/discover/{name}")
    async def discover(name: str):
        await daemon.reconcile()
        daemon.admitted(name)
        result = await daemon.pool.discover({"server": name}, {})
        daemon.notify()
        return result

    @app.post("/v1/calls")
    async def call(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1048576:
                raise DomainError("INVALID_TOOL_ARGUMENTS")
        try:
            value = json.loads(body)
        except ValueError:
            raise DomainError("INVALID_TOOL_ARGUMENTS") from None
        return await daemon.call(value)

    @app.post("/v1/calls/{call_id}/cancel")
    async def cancel(call_id: str):
        task = daemon.calls.get(call_id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return {"cancelled": task is not None}

    return app


async def serve(args):
    os.umask(0o077)
    path = args.socket
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise RuntimeError("MCP_SOCKET_DIRECTORY_UNSAFE")
    descriptor = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("MCP_DAEMON_ALREADY_RUNNING") from None
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
                raise RuntimeError("MCP_SOCKET_PATH_CONFLICT")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                try:
                    probe.connect(str(path))
                except ConnectionRefusedError:
                    pass
                else:
                    raise RuntimeError("MCP_SOCKET_ALREADY_LISTENING")
            path.unlink()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as bound:
            bound.bind(str(path))
            os.chmod(path, 0o600)
            bound.listen(128)
            bound.setblocking(False)
            app = create_app(MCPDaemon(args.data_root, args.config))
            server = uvicorn.Server(
                uvicorn.Config(app, uds=str(path), log_level="warning", timeout_graceful_shutdown=3)
            )
            await server.serve(sockets=[bound])
    finally:
        os.close(descriptor)


def main():
    parser = argparse.ArgumentParser(description="Roami independent MCP daemon")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--socket", type=Path, required=True)
    asyncio.run(serve(parser.parse_args()))


if __name__ == "__main__":
    main()
