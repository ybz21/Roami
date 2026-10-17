"Lazy MCP connections; each actor owns its SDK task groups for their whole lifetime."

import asyncio
import hashlib
import logging
import os
import re
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft202012Validator
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.tools.mcp_results import MCPResults

log = logging.getLogger(__name__)


def validate_servers(configs):
    if not isinstance(configs, dict) or len(configs) > 16:
        raise DomainError("INVALID_MCP_CONFIG")
    for name, config in configs.items():
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[a-z][a-z0-9_-]{0,19}", name)
            or not isinstance(config, dict)
        ):
            raise DomainError("INVALID_MCP_CONFIG")
        transport = config.get("transport", "stdio")
        if transport == "stdio":
            if not isinstance(config.get("command"), str) or not config["command"]:
                raise DomainError("INVALID_MCP_CONFIG")
            if not isinstance(config.get("args", []), list) or not all(
                isinstance(arg, str) for arg in config.get("args", [])
            ):
                raise DomainError("INVALID_MCP_CONFIG")
        elif transport == "streamable_http":
            parsed = urlsplit(config.get("url", ""))
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.fragment
                or parsed.query
                or (
                    parsed.scheme == "http"
                    and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                )
            ):
                raise DomainError("INVALID_MCP_CONFIG")
        else:
            raise DomainError("INVALID_MCP_CONFIG")
        for key in ["env_env", "header_env"]:
            mapping = config.get(key, {})
            if not isinstance(mapping, dict) or not all(
                isinstance(k, str) and isinstance(v, str) and k and v for k, v in mapping.items()
            ):
                raise DomainError("INVALID_MCP_CONFIG")
        timeout = config.get("timeout_seconds", 30)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 1 <= timeout <= 45
        ):
            raise DomainError("INVALID_MCP_CONFIG")
        if "key_env" in config and (
            not isinstance(config["key_env"], str) or not config["key_env"]
        ):
            raise DomainError("INVALID_MCP_CONFIG")
        if not isinstance(config.get("read_only", []), list) or not all(
            isinstance(name, str) for name in config.get("read_only", [])
        ):
            raise DomainError("INVALID_MCP_CONFIG")


@dataclass
class Request:
    operation: str
    args: dict
    future: asyncio.Future
    started: bool = False
    dispatched: bool = False
    protocol_id: int | str | None = None


@dataclass
class Connection:
    name: str
    config: dict
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(32))
    task: asyncio.Task | None = None
    ready: asyncio.Future | None = None
    names: dict = field(default_factory=dict)
    version: str = ""
    retry_after: float = 0
    failures: int = 0
    current: Request | None = None
    session: ClientSession | None = None


class TrackedStream:
    def __init__(self, stream, connection):
        self.stream, self.connection = stream, connection

    async def send(self, message):
        packet = message.message.root
        current = self.connection.current
        if current and isinstance(packet, types.JSONRPCRequest) and packet.method == "tools/call":
            current.protocol_id = packet.id
        await self.stream.send(message)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.stream.aclose()


class MCPConnections:
    def __init__(self, registry, configs, artifacts=None):
        validate_servers(configs)
        self.results = MCPResults(artifacts)
        self.registry = registry
        self.connections = {name: Connection(name, config) for name, config in configs.items()}
        self.closed = False
        if configs:
            registry.add(
                Tool(
                    "mcp_discover",
                    "Discover or refresh configured MCP tools before use. Servers: "
                    + ", ".join(configs),
                    object_schema(
                        {"server": {"type": "string", "enum": list(configs)}}, ["server"]
                    ),
                    self.discover,
                )
            )

    def _remove(self, connection):
        for name in connection.names:
            self.registry.registry.pop(name, None)
        connection.names = {}
        connection.version = ""

    async def _catalog(self, connection, session):
        tools, cursor, seen = [], None, set()
        for _ in range(16):
            page = await session.list_tools(params=types.PaginatedRequestParams(cursor=cursor))
            tools.extend(page.tools)
            if len(tools) > 256:
                raise DomainError("MCP_CATALOG_LIMIT")
            cursor = page.nextCursor
            if not cursor:
                break
            if cursor in seen:
                raise DomainError("MCP_INVALID_CATALOG")
            seen.add(cursor)
        else:
            raise DomainError("MCP_CATALOG_LIMIT")
        prepared, names, remote_names = [], {}, set()
        for remote in tools:
            schema = remote.inputSchema
            if remote.name in remote_names or schema.get("type") != "object":
                raise DomainError("MCP_INVALID_CATALOG")
            remote_names.add(remote.name)
            serialized = encoded(schema)
            if len(serialized.encode()) > 32_000:
                raise DomainError("MCP_CATALOG_LIMIT")
            self._check_refs(schema)
            Draft202012Validator.check_schema(schema)
            effect = "read" if remote.name in connection.config.get("read_only", []) else "write"
            description = (remote.description or remote.name)[:2000]
            digest = hashlib.sha256(
                encoded([remote.name, schema, description, effect]).encode()
            ).hexdigest()
            slug = re.sub(r"[^a-zA-Z0-9_-]", "_", remote.name)[:24]
            alias = f"mcp_{connection.name}_{slug}_{digest[:10]}"

            async def invoke(
                args, binding, alias=alias, connection=connection, remote_name=remote.name
            ):
                answer = await self._request(
                    connection,
                    "call",
                    {"alias": alias, "arguments": args, "progress": binding.get("progress")},
                )
                try:
                    return await self.results.project(answer, binding, connection.name, remote_name)
                except (DomainError, OSError):
                    raise DomainError("MCP_OUTCOME_UNKNOWN") from None

            prepared.append(Tool(alias, description, schema, invoke, effect=effect))
            names[alias] = remote.name
        version = hashlib.sha256(encoded(sorted(names)).encode()).hexdigest()
        self._remove(connection)
        for tool in sorted(prepared, key=lambda item: item.name):
            self.registry.add(tool)
        connection.names, connection.version = names, version
        return self._view(connection)

    @classmethod
    def _check_refs(cls, value):
        if isinstance(value, dict):
            if "$ref" in value and not str(value["$ref"]).startswith("#"):
                raise DomainError("MCP_EXTERNAL_SCHEMA_REFERENCE")
            for nested in value.values():
                cls._check_refs(nested)
        elif isinstance(value, list):
            for nested in value:
                cls._check_refs(nested)

    def _view(self, connection):
        return {
            "server": connection.name,
            "catalogVersion": connection.version,
            "tools": sorted(connection.names),
        }

    async def discover(self, args, binding):
        connection = self.connections[args["server"]]
        return await self._request(connection, "discover", {})

    async def _ensure(self, connection):
        if self.closed:
            raise DomainError("MCP_CLOSED")
        if connection.task is None or connection.task.done():
            if time.monotonic() < connection.retry_after:
                raise DomainError("MCP_RECONNECT_BACKOFF")
            connection.ready = asyncio.get_running_loop().create_future()
            connection.task = asyncio.create_task(
                self._actor(connection), name="mcp-" + connection.name
            )
        await asyncio.shield(connection.ready)

    async def _request(self, connection, operation, args):
        request = Request(operation, args, asyncio.get_running_loop().create_future())
        try:
            async with asyncio.timeout(connection.config.get("timeout_seconds", 30)):
                await self._ensure(connection)
                try:
                    connection.queue.put_nowait(request)
                except asyncio.QueueFull:
                    raise DomainError("MCP_BUSY") from None
                return await asyncio.shield(request.future)
        except (TimeoutError, asyncio.CancelledError) as exc:
            request.future.cancel()
            if request.protocol_id is not None and connection.session:
                try:
                    async with asyncio.timeout(1):
                        await connection.session.send_notification(
                            types.ClientNotification(
                                types.CancelledNotification(
                                    params=types.CancelledNotificationParams(
                                        requestId=request.protocol_id,
                                        reason="Roami call interrupted",
                                    ),
                                )
                            )
                        )
                except Exception:  # noqa: BLE001
                    log.debug("MCP cancellation transport unavailable")
            if connection.task and (
                request.started or (connection.ready and not connection.ready.done())
            ):
                if not connection.task.cancelling():
                    connection.task.cancel()
                await asyncio.gather(connection.task, return_exceptions=True)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise DomainError(
                "MCP_OUTCOME_UNKNOWN" if request.dispatched else "MCP_TIMEOUT"
            ) from None

    async def _actor(self, connection):
        request = None
        try:
            async with AsyncExitStack() as stack:
                config = connection.config
                if config.get("transport", "stdio") == "stdio":
                    env = self._environment(config.get("env_env", {}))
                    errlog = stack.enter_context(await asyncio.to_thread(open, os.devnull, "w"))
                    streams = await stack.enter_async_context(
                        stdio_client(
                            StdioServerParameters(
                                command=config["command"],
                                args=config.get("args", []),
                                env=env,
                                cwd=config.get("cwd"),
                            ),
                            errlog=errlog,
                        )
                    )
                else:
                    headers = self._environment(config.get("header_env", {}))
                    if config.get("key_env"):
                        headers["Authorization"] = (
                            "Bearer " + self._environment({"key": config["key_env"]})["key"]
                        )
                    client = await stack.enter_async_context(
                        httpx.AsyncClient(headers=headers, timeout=10, follow_redirects=False)
                    )
                    streams = await stack.enter_async_context(
                        streamable_http_client(config["url"], http_client=client)
                    )

                async def changed(notification):
                    if isinstance(notification, Exception):
                        self._remove(connection)
                    if isinstance(notification, types.ServerNotification) and isinstance(
                        notification.root, types.ToolListChangedNotification
                    ):
                        self._remove(connection)

                session = await stack.enter_async_context(
                    ClientSession(
                        streams[0],
                        TrackedStream(streams[1], connection),
                        read_timeout_seconds=timedelta(seconds=config.get("timeout_seconds", 30)),
                        message_handler=changed,
                    )
                )
                connection.session = session
                await session.initialize()
                await self._catalog(connection, session)
                connection.failures = 0
                if not connection.ready.done():
                    connection.ready.set_result(True)
                while True:
                    request = await connection.queue.get()
                    if request.future.cancelled():
                        continue
                    connection.current = request
                    request.started = True
                    await self._catalog(connection, session)
                    if request.operation == "discover":
                        result = self._view(connection)
                    else:
                        remote = connection.names.get(request.args["alias"])
                        if not remote:
                            request.future.set_exception(DomainError("TOOL_UNAVAILABLE"))
                            connection.current = None
                            continue
                        request.dispatched = True
                        answer = await session.call_tool(
                            remote,
                            request.args["arguments"],
                            progress_callback=request.args.get("progress"),
                        )
                        if answer.isError:
                            raise DomainError("MCP_OUTCOME_UNKNOWN")
                        result = answer
                    if not request.future.done():
                        request.future.set_result(result)
                    connection.current = None
        except (Exception, asyncio.CancelledError):  # noqa: BLE001
            # Protocol/server errors may echo credentials or prompts; expose stable codes only.
            if request and not request.future.done():
                request.future.set_exception(
                    DomainError("MCP_OUTCOME_UNKNOWN" if request.dispatched else "MCP_UNAVAILABLE")
                )
        finally:
            connection.session = None
            connection.current = None
            self._remove(connection)
            connection.failures += 1
            connection.retry_after = time.monotonic() + min(
                30, 2 ** min(connection.failures - 1, 5)
            )
            if not connection.ready.done():
                connection.ready.set_exception(DomainError("MCP_UNAVAILABLE"))
                connection.ready.exception()
            while not connection.queue.empty():
                waiting = connection.queue.get_nowait()
                if not waiting.future.done():
                    waiting.future.set_exception(DomainError("MCP_UNAVAILABLE"))

    @staticmethod
    def _environment(mapping):
        if any(name not in os.environ for name in mapping.values()):
            raise DomainError("MCP_CREDENTIAL_MISSING")
        return {key: os.environ[name] for key, name in mapping.items()}

    async def close(self):
        self.closed = True
        tasks = [c.task for c in self.connections.values() if c.task and not c.task.done()]
        for task in tasks:
            if not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
