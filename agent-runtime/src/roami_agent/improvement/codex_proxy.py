"""Per-operation loopback bridge for Codex's Responses requests and shared billing."""

import asyncio
import hmac
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from roami_agent.protocol.errors import DomainError
from roami_agent.providers.model_proxy import ProxyTransport


@asynccontextmanager
async def codex_route(proxy, selected, env, role, *, outcome=None):
    if proxy is None:
        yield selected, env
        return
    name = selected.get("model_provider") or "roami_rsi"
    prefix = "model_providers." + name + "."
    upstream = selected.get(prefix + "base_url")
    if not upstream:
        if name not in {"openai", "roami_rsi"}:
            raise DomainError("RSI_CODEX_PROVIDER_CONFIG_UNSUPPORTED")
        home = Path(env.get("CODEX_HOME", str(Path(env.get("HOME", str(Path.home()))) / ".codex")))
        authentication = home / "auth.json"
        mode = (
            json.loads(authentication.read_text()).get("auth_mode")
            if authentication.is_file()
            else None
        )
        upstream = (
            "https://chatgpt.com/backend-api/codex"
            if mode == "chatgpt"
            else "https://api.openai.com/v1"
        )
    async with CodexProxy(
        proxy, upstream, role, selected.get("model", "codex-default"), outcome=outcome
    ) as bridge:
        settings = {
            **selected,
            "model_provider": name,
            prefix + "name": "Roami RSI",
            prefix + "base_url": bridge.url,
            prefix + "wire_api": "responses",
            prefix + "request_max_retries": 0,
            prefix + "stream_max_retries": 0,
            prefix + "env_http_headers": {
                **selected.get(prefix + "env_http_headers", {}),
                "X-Roami-Rsi-Key": "ROAMI_RSI_CODEX_PROXY_KEY",
            },
        }
        if not selected.get("model_provider"):
            settings[prefix + "requires_openai_auth"] = True
        yield settings, {**env, "ROAMI_RSI_CODEX_PROXY_KEY": bridge.secret}


class CodexProxy:
    def __init__(self, proxy, upstream, role, model, *, upstream_client=None, outcome=None):
        self.proxy, self.upstream, self.role, self.model = proxy, upstream.rstrip("/"), role, model
        self.secret = secrets.token_hex(32)
        self.server = None
        self.clients = set()
        self.client = None
        self.upstream_client = upstream_client
        self.outcome = outcome if outcome is not None else {}
        self.outcome["responses"] = 0
        self.outcome["attempts"] = 0

    def attempted(self):
        self.outcome["attempts"] += 1

    async def __aenter__(self):
        upstream = self.upstream_client or httpx.AsyncClient(
            timeout=httpx.Timeout(180, connect=15), follow_redirects=False
        )
        self.client = httpx.AsyncClient(
            transport=ProxyTransport(
                self.proxy,
                upstream,
                "rsi_codex_" + self.role,
                self.model,
                on_attempt=self.attempted,
            ),
            timeout=upstream.timeout,
            follow_redirects=False,
        )
        try:
            self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0, limit=65536)
        except BaseException:
            await self.client.aclose()
            raise
        port = self.server.sockets[0].getsockname()[1]
        self.url = "http://127.0.0.1:" + str(port)
        return self

    async def __aexit__(self, *exc):
        self.server.close()
        await self.server.wait_closed()
        pending = list(self.clients)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await self.client.aclose()

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.clients.add(task)
        sent = False
        response = None
        try:
            async with asyncio.timeout(30):
                raw = await reader.readuntil(b"\r\n\r\n")
                lines = raw.decode("latin1").split("\r\n")
                method, path, _ = lines[0].split(" ")
                headers = {}
                for line in lines[1:]:
                    if not line:
                        continue
                    key, separator, value = line.partition(":")
                    if not separator or key.lower() in headers:
                        raise DomainError("RSI_CODEX_PROXY_REQUEST")
                    headers[key.lower()] = value.strip()
                if not hmac.compare_digest(headers.pop("x-roami-rsi-key", ""), self.secret):
                    raise DomainError("RSI_CODEX_PROXY_AUTH")
                if method != "POST" or path not in {"/responses", "/responses/compact"}:
                    raise DomainError("RSI_CODEX_PROXY_ROUTE")
                length = headers.get("content-length", "")
                if (
                    "transfer-encoding" in headers
                    or not length.isdigit()
                    or not 0 < int(length) <= 2_000_000
                ):
                    raise DomainError("RSI_CODEX_PROXY_SIZE")
                body = await reader.readexactly(int(length))
            for key in ("host", "connection", "content-length", "accept-encoding"):
                headers.pop(key, None)
            request = self.client.build_request(
                "POST", self.upstream + path, content=body, headers=headers
            )
            response = await self.client.send(request, stream=True)
            self.outcome["responses"] += 1
            writer.write(
                f"HTTP/1.1 {response.status_code} {response.reason_phrase}\r\n".encode("ascii")
            )
            for key, value in response.headers.items():
                if key.lower() not in {
                    "connection",
                    "content-length",
                    "transfer-encoding",
                    "content-encoding",
                }:
                    writer.write(f"{key}: {value}\r\n".encode("latin1"))
            writer.write(b"Connection: close\r\n\r\n")
            sent = True
            await writer.drain()
            async for chunk in response.aiter_bytes():
                writer.write(chunk)
                await writer.drain()
        except (
            DomainError,
            ValueError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
            TimeoutError,
            httpx.HTTPError,
        ) as error:
            self.outcome["error_code"] = getattr(error, "code", "RSI_CODEX_PROXY_FAILED")
            if not sent:
                body = json.dumps(
                    {"error": {"code": getattr(error, "code", "RSI_CODEX_PROXY_FAILED")}}
                ).encode()
                writer.write(
                    b"HTTP/1.1 429 Too Many Requests\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n"
                    + body
                )
                await writer.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            try:
                if response is not None:
                    await response.aclose()
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                self.clients.discard(task)
