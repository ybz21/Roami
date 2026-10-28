"""The private bridge accepts supported images and preserves pre-provider failures."""

import asyncio
import base64
import io
import json
import random
from pathlib import Path

import httpx
import pytest
from PIL import Image

from roami_agent.improvement.evaluation.execution import containers
from roami_agent.improvement.evaluation.protocol_suite import protocol_suite
from roami_agent.improvement.evaluation.trial_evidence import trial_summary
from roami_agent.improvement.integrations.model_gateway import ModelGateway
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings


async def test_supported_image_reaches_provider_without_changing_messages(tmp_path):
    image = Image.frombytes("RGB", (800, 700), random.Random(0).randbytes(800 * 700 * 3))
    png = io.BytesIO()
    image.save(png, format="PNG")
    assert len(png.getvalue()) < 2 * 1024 * 1024
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64," + base64.b64encode(png.getvalue()).decode()
                    },
                }
            ],
        }
    ]
    body = {"messages": messages, "tools": []}
    assert len(json.dumps(body).encode()) > 2_000_000
    calls = []

    class Provider:
        async def stream(self, received, tools):
            calls.append((received, tools))
            yield ModelEvent("text", "image received")

    socket = tmp_path / "model.sock"
    async with ModelGateway(socket, {"worker": Provider()}) as gateway:
        async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(socket))) as client:
            response = await client.post("http://localhost/v1/worker/chat/completions", json=body)
        assert response.status_code == 200, response.text
        assert "image received" in response.text
        assert calls == [(messages, [])] and gateway.errors == []


@pytest.mark.parametrize("body", [[], None, "invalid"])
async def test_non_object_requests_have_a_failure_receipt(tmp_path, body):
    socket = tmp_path / "model.sock"
    async with ModelGateway(socket, {}) as gateway:
        async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(socket))) as client:
            response = await client.post(
                "http://localhost/v1/main/chat/completions",
                content=json.dumps(body),
            )
        assert response.status_code == 400
        assert response.json() == {"error": {"code": "RSI_GATEWAY_INPUT"}}
        assert gateway.errors == ["RSI_GATEWAY_INPUT"]


async def test_timeout_retains_gateway_errors_without_inventing_provider_usage(
    tmp_path, monkeypatch
):
    socket = None
    removed = []

    async def docker(*args, **kwargs):
        nonlocal socket
        if args[0] == "create":
            mount = next(a for a in args if "dst=/model," in a)
            socket = Path(mount.split("src=", 1)[1].split(",", 1)[0]) / "gateway.sock"
        if args[0] == "start":
            for _ in range(2):
                reader, writer = await asyncio.open_unix_connection(socket)
                writer.write(
                    b"POST /v1/main/chat/completions HTTP/1.1\r\nContent-Length: "
                    + str(16 * 1024 * 1024 + 1).encode()
                    + b"\r\n\r\n"
                )
                await writer.drain()
                try:
                    response = await asyncio.wait_for(reader.read(), timeout=3)
                    assert json.loads(response.split(b"\r\n\r\n", 1)[1]) == {
                        "error": {"code": "RSI_GATEWAY_SIZE"}
                    }
                finally:
                    writer.close()
                    await writer.wait_closed()
            raise TimeoutError("private failure detail must not enter evidence")
        return b""

    async def remove(*args):
        removed.append(args)

    def forbidden(*args):
        pytest.fail("Rejected bridge requests must not call a provider")

    monkeypatch.setattr(containers, "docker_command", docker)
    executor = containers.ContainerExecutor(Settings(), provider_factory=forbidden)
    executor.image_id = "fixture-image"
    monkeypatch.setattr(executor, "remove", remove)
    case = protocol_suite()["cases"][0]
    result = await executor.run(case, {}, tmp_path)
    assert result["grade"]["reason"] == "RSI_TIME_BUDGET" and removed
    receipt = json.loads((tmp_path / "model-log.json").read_text())
    assert receipt["gateway_errors"] == [{"code": "RSI_GATEWAY_SIZE", "count": 2}]
    assert receipt["requests"] == [] and result["metrics"]["model_calls"] == 0
    assert "private failure detail" not in json.dumps(receipt)
    summary = trial_summary(case, result, tmp_path)
    assert {"RSI_TIME_BUDGET", "RSI_GATEWAY_SIZE"} <= set(summary["signals"])


async def test_oversized_header_is_rejected_before_provider_admission(tmp_path):
    socket = tmp_path / "model.sock"
    async with ModelGateway(socket, {}) as gateway:
        reader, writer = await asyncio.open_unix_connection(socket)
        writer.write(b"POST /v1/main/chat/completions HTTP/1.1\r\nX-Fill: " + b"x" * 70_000)
        await writer.drain()
        try:
            response = await asyncio.wait_for(reader.read(), timeout=1)
            assert b"RSI_GATEWAY_SIZE" in response
            assert gateway.errors == ["RSI_GATEWAY_SIZE"]
        finally:
            writer.close()
            await writer.wait_closed()


async def test_invalid_json_does_not_echo_input(tmp_path):
    socket = tmp_path / "model.sock"
    async with ModelGateway(socket, {}) as gateway:
        async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(socket))) as client:
            response = await client.post(
                "http://localhost/v1/main/chat/completions", content=b"private input, invalid JSON"
            )
        assert response.json() == {"error": {"code": "RSI_GATEWAY_INPUT"}}
        assert gateway.errors == ["RSI_GATEWAY_INPUT"]


async def test_provider_exception_details_are_not_gateway_error_codes(tmp_path):
    class Provider:
        async def stream(self, messages, tools):
            yield ModelEvent("text", "partial")
            raise DomainError("https://private.invalid/request?credential=do-not-disclose")

    socket = tmp_path / "model.sock"
    async with ModelGateway(socket, {"main": Provider()}) as gateway:
        async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(socket))) as client:
            response = await client.post(
                "http://localhost/v1/main/chat/completions", json={"messages": []}
            )
        assert response.status_code == 200 and "RSI_GATEWAY_FAILED" in response.text
        assert "private.invalid" not in response.text
        assert gateway.errors == ["RSI_GATEWAY_FAILED"]
