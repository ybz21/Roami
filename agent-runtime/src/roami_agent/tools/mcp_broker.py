"""Agent-side access to MCP connections owned by a separate node daemon."""

import asyncio
import json
import os
import stat
import uuid
from pathlib import Path

import httpx
from mcp import types

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded


def node_socket(data_root):
    if os.environ.get("ROAMI_MCP_SOCKET"):
        return Path(os.environ["ROAMI_MCP_SOCKET"])
    path = Path(data_root) / "agents/mcp-daemon.json"
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
        or info.st_size > 4096
    ):
        raise DomainError("MCP_CONFIGURATION_INVALID")
    try:
        value = json.loads(path.read_text())
        socket_path = Path(value["socket"])
        if value["version"] != 1 or not socket_path.is_absolute():
            raise ValueError
        return socket_path
    except (ValueError, KeyError, TypeError):
        raise DomainError("MCP_CONFIGURATION_INVALID") from None


def config_fingerprint(config):
    import hashlib

    return hashlib.sha256(encoded({"transport": "stdio", **config}).encode()).hexdigest()


class CatalogSession:
    def __init__(self, tools):
        self.tools = tools

    async def list_tools(self, params):
        return types.ListToolsResult(tools=[types.Tool.model_validate(tool) for tool in self.tools])


class MCPBroker:
    def __init__(self, socket_path, *, data_root=None):
        self.socket_path = socket_path
        headers = {}
        if data_root is not None:
            import hashlib

            headers["X-Roami-Instance"] = hashlib.sha256(
                str(Path(data_root).resolve()).encode()
            ).hexdigest()
        self.client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=str(socket_path), retries=0),
            base_url="http://roami-mcp",
            trust_env=False,
            headers=headers,
            timeout=httpx.Timeout(35, connect=2, write=10, pool=2),
        )
        self.lock = asyncio.Lock()
        self.watcher = None
        self.revision = ""
        self.epoch = 0

    def start(self, pool):
        if self.watcher is None or self.watcher.done():
            self.watcher = asyncio.create_task(self._watch(pool), name="mcp-broker-events")

    def check_socket(self):
        try:
            info = self.socket_path.lstat()
            parent = self.socket_path.parent.lstat()
            if (
                not stat.S_ISSOCK(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_mode & 0o077
                or not stat.S_ISDIR(parent.st_mode)
                or parent.st_uid != os.geteuid()
                or parent.st_mode & 0o077
            ):
                raise OSError
        except OSError:
            raise DomainError("MCP_DAEMON_UNAVAILABLE") from None

    async def _json(self, method, path, **kwargs):
        self.check_socket()
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.HTTPError:
            raise DomainError("MCP_DAEMON_UNAVAILABLE") from None
        if response.is_error:
            raise DomainError(response.json().get("error", {}).get("code", "MCP_UNAVAILABLE"))
        return response.json()

    def _unavailable(self, pool):
        self.revision = ""
        for connection in pool.connections.values():
            connection.remote_state = "reconnecting" if connection.enabled else "not_connected"
            connection.remote_busy = False
            pool._remove(connection)

    async def _apply(self, pool, snapshot):
        for name, connection in list(pool.connections.items()):
            state = snapshot["servers"].get(name)
            if not state or state["fingerprint"] != config_fingerprint(connection.config):
                connection.remote_state = "reconnecting" if connection.enabled else "not_connected"
                pool._remove(connection)
                continue
            connection.remote_state = state["state"]
            connection.remote_busy = state["busy"]
            if state["state"] != "connected":
                pool._remove(connection)
            elif connection.version != state["catalogVersion"]:
                catalog = await self._json("GET", "/v1/catalog/" + name)
                if catalog["fingerprint"] != config_fingerprint(connection.config):
                    pool._remove(connection)
                    connection.remote_state = "reconnecting"
                    continue
                await pool._catalog(connection, CatalogSession(catalog["tools"]))
        self.revision = snapshot["revision"]

    async def refresh(self, pool, *, sync=False):
        async with self.lock:
            self.epoch += 1
            try:
                snapshot = await self._json("POST" if sync else "GET", "/v1/state", timeout=3)
                await self._apply(pool, snapshot)
            except (httpx.HTTPError, DomainError, ValueError):
                self._unavailable(pool)

    async def _watch(self, pool):
        delay = 0.25
        while not pool.closed:
            epoch = self.epoch
            try:
                snapshot = await self._json("GET", "/v1/state", params={"since": self.revision})
                async with self.lock:
                    if epoch == self.epoch:
                        await self._apply(pool, snapshot)
                delay = 0.25
            except (httpx.HTTPError, DomainError, ValueError):
                async with self.lock:
                    if epoch == self.epoch:
                        self._unavailable(pool)
                await asyncio.sleep(delay)
                delay = min(8, delay * 2)

    async def request(self, pool, connection, operation, args):
        if operation == "discover":
            await self._json("POST", "/v1/discover/" + connection.name)
            await self.refresh(pool)
            if connection.remote_state != "connected":
                raise DomainError("MCP_UNAVAILABLE")
            return pool._view(connection)
        call_id = uuid.uuid4().hex
        connection.current = asyncio.current_task()
        dispatched = False
        try:
            self.check_socket()
            async with asyncio.timeout(connection.config.get("timeout_seconds", 0) or None):
                async with self.client.stream(
                    "POST",
                    "/v1/calls",
                    json={
                        "callId": call_id,
                        "server": connection.name,
                        "fingerprint": config_fingerprint(connection.config),
                        "alias": args["alias"],
                        "arguments": args["arguments"],
                    },
                    timeout=None,
                ) as response:
                    dispatched = True
                    if response.is_error:
                        await response.aread()
                        raise DomainError(
                            response.json().get("error", {}).get("code", "MCP_UNAVAILABLE")
                        )
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        event = json.loads(line)
                        if event["kind"] == "result":
                            return types.CallToolResult.model_validate(event["result"])
                        if event["kind"] == "error":
                            raise DomainError(event["code"])
                        if event["kind"] == "progress" and args.get("progress"):
                            await args["progress"](
                                event["progress"], event.get("total"), event.get("message")
                            )
            raise DomainError("MCP_OUTCOME_UNKNOWN")
        except (asyncio.CancelledError, TimeoutError) as error:
            if not pool.shutting_down:
                try:
                    await self._json("POST", "/v1/calls/" + call_id + "/cancel", timeout=2)
                except (httpx.HTTPError, DomainError):
                    pass
            if isinstance(error, asyncio.CancelledError):
                raise
            raise DomainError("MCP_OUTCOME_UNKNOWN" if dispatched else "MCP_TIMEOUT") from None
        except httpx.ConnectError:
            raise DomainError("MCP_DAEMON_UNAVAILABLE") from None
        except (httpx.HTTPError, ValueError):
            raise DomainError("MCP_OUTCOME_UNKNOWN") from None
        finally:
            connection.current = None

    async def close(self):
        if self.watcher:
            self.watcher.cancel()
            await asyncio.gather(self.watcher, return_exceptions=True)
        await self.client.aclose()
