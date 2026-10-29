"""Configured model clients use the private Go socket and never fall back to cloud."""

import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from test_model_proxy import EVENTS, consume

from roami_agent.protocol.errors import DomainError, ModelAdmissionRejected
from roami_agent.providers.factory import configured_provider
from roami_agent.server.configuration import Settings


@asynccontextmanager
async def gateway_fixture(socket, seen, *, status=200, code=None):
    async def handle(reader, writer):
        try:
            raw = await reader.readuntil(b"\r\n\r\n")
            lines = raw.decode().split("\r\n")
            headers = dict(line.lower().split(": ", 1) for line in lines[1:] if line)
            body = await reader.readexactly(int(headers["content-length"]))
            seen.append((lines[0], headers, json.loads(body)))
            payload = EVENTS if status == 200 else b"{}"
            response = (
                f"HTTP/1.1 {status} Fixture\r\nContent-Type: text/event-stream\r\n"
                f"Content-Length: {len(payload)}\r\nConnection: close\r\n"
            )
            if code:
                response += f"X-Roami-Model-Error: {code}\r\n"
            writer.write(response.encode() + b"\r\n" + payload)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_unix_server(handle, path=socket)
    try:
        yield
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.parametrize("role", ["main", "worker", "memory"])
async def test_factory_preserves_route_and_uses_local_socket(tmp_path, monkeypatch, role):
    socket = str(tmp_path / "model.sock")
    monkeypatch.setenv("ROAMI_MODEL_GATEWAY_SOCKET", socket)
    monkeypatch.setenv("MODEL_FIXTURE_CREDENTIAL", "fixture")
    settings = Settings(
        endpoint="https://must-not-connect.invalid/gateway/v1",
        model="fixture",
        key_env="MODEL_FIXTURE_CREDENTIAL",
    )
    seen = []
    async with gateway_fixture(socket, seen):
        provider = configured_provider(settings, role)
        try:
            await consume(provider)
        finally:
            await provider.close()
    line, headers, body = seen[0]
    assert line == "POST /v1/chat/completions HTTP/1.1"
    assert headers["x-roami-model-role"] == role
    assert (
        headers["x-roami-model-upstream"]
        == "https://must-not-connect.invalid/gateway/v1/chat/completions"
    )
    assert headers["authorization"] == "bearer fixture"
    assert body["model"] == "fixture" and body["stream"] is True


@pytest.mark.parametrize(
    "status,code",
    [
        (402, "MODEL_PROXY_DAILY_LIMIT"),
        (409, "MODEL_PROXY_USAGE_UNKNOWN"),
        (409, "MODEL_PROXY_USAGE_PENDING"),
    ],
)
async def test_local_quota_rejection_is_not_retried(tmp_path, monkeypatch, status, code):
    socket = str(tmp_path / "model.sock")
    monkeypatch.setenv("ROAMI_MODEL_GATEWAY_SOCKET", socket)
    seen = []
    async with gateway_fixture(socket, seen, status=status, code=code):
        provider = configured_provider(
            Settings(endpoint="https://must-not-connect.invalid/v1", model="fixture"), "main"
        )
        try:
            expected = "MODEL_PROXY_USAGE_UNKNOWN" if code == "MODEL_PROXY_USAGE_PENDING" else code
            with pytest.raises(ModelAdmissionRejected, match=expected):
                await consume(provider)
        finally:
            await provider.close()
    assert len(seen) == 1


async def test_unavailable_local_gateway_does_not_bypass_accounting(tmp_path, monkeypatch):
    monkeypatch.setenv("ROAMI_MODEL_GATEWAY_SOCKET", str(tmp_path / "missing.sock"))
    provider = configured_provider(
        Settings(endpoint="https://must-not-connect.invalid/v1", model="fixture", model_retries=0),
        "main",
    )
    try:
        with pytest.raises(DomainError, match="MODEL_TRANSPORT_FAILED"):
            await consume(provider)
    finally:
        await provider.close()


async def test_explicit_container_bridge_transport_is_preserved(monkeypatch):
    monkeypatch.setenv("ROAMI_MODEL_GATEWAY_SOCKET", "/unmounted-host-socket")
    seen = []

    def upstream(request):
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=EVENTS)

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    provider = configured_provider(
        Settings(endpoint="http://localhost/v1/main", model="fixture"),
        "main",
        client=client,
    )
    try:
        await consume(provider)
    finally:
        await provider.close()
    assert len(seen) == 1
    assert str(seen[0].url) == "http://localhost/v1/main/chat/completions"
