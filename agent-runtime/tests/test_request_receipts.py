"""Safe Go receipts survive direct calls and the private relay, including failures."""

import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from test_model_error_telemetry import PrivateBody

from roami_agent.improvement.integrations.measurements import EpisodeBudget, MeteredModel
from roami_agent.improvement.integrations.model_gateway import ModelGateway
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.providers.chat_completions import ChatCompletions
from roami_agent.providers.local_gateway import LocalGatewayTransport
from roami_agent.providers.model_bridge_transport import PrivateModelBridgeTransport
from roami_agent.providers.request_receipts import forwarded_receipt

INPUT = json.loads(
    (Path(__file__).parents[2] / "cases/case-62-mech-rc01/input/receipts.json").read_text()
)
CALL = INPUT["retry_scenario"][0]["call_id"]


@asynccontextmanager
async def go_response(tmp_path, responses):
    import asyncio

    socket = tmp_path / "go.sock"
    calls = []

    async def handle(reader, writer):
        try:
            raw = await reader.readuntil(b"\r\n\r\n")
            headers = dict(
                line.lower().split(": ", 1) for line in raw.decode().split("\r\n")[1:] if line
            )
            await reader.readexactly(int(headers["content-length"]))
            calls.append(headers)
            status, call_id = responses[len(calls) - 1]
            success = {
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": INPUT["successful_usage"]["input_tokens"],
                    "completion_tokens": INPUT["successful_usage"]["output_tokens"],
                },
            }
            payload = (
                b"{}"
                if status != 200
                else b"data: " + json.dumps(success).encode() + b"\n\ndata: [DONE]\n\n"
            )
            prefix = f"HTTP/1.1 {status} Fixture\r\nContent-Type: text/event-stream\r\nContent-Length: {len(payload)}\r\nRetry-After: 0\r\nX-Roami-Model-Call: {call_id}\r\nX-Request-Id: upstream-{len(calls)}\r\nConnection: close\r\n\r\n"
            writer.write(prefix.encode() + payload)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_unix_server(handle, path=str(socket))
    try:
        yield socket, calls
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.parametrize("status", [200, 401, 403, 503, 302])
async def test_private_go_transport_records_call_id_and_http_status(tmp_path, status):
    events = []
    async with go_response(tmp_path, [(status, CALL)]) as (socket, calls):
        async with httpx.AsyncClient(
            transport=LocalGatewayTransport(str(socket), "worker")
        ) as client:
            provider = ChatCompletions(
                "http://localhost/v1", "fixture", client=client, max_retries=0
            )
            if status == 200:
                events = [event async for event in provider.stream([], [])]
            else:
                with pytest.raises(DomainError):
                    async for event in provider.stream([], []):
                        events.append(event)
        assert len(calls) == 1
    receipt = next(
        e.value for e in events if e.kind == "telemetry" and e.value["phase"] == "headers"
    )
    assert receipt == {
        "phase": "headers",
        "attempt": 1,
        "httpStatus": status,
        "requestId": "upstream-1",
        "gatewayCallId": CALL,
    }
    if status != 200:
        assert not any(e.kind in {"usage", "text", "tool"} for e in events)


async def test_external_provider_cannot_claim_a_go_receipt_or_relay_metadata():
    events = []
    metadata = {"phase": "headers", "attempt": 1, "gatewayCallId": CALL, "httpStatus": 401}
    body = (
        "data: "
        + json.dumps({"choices": [], "roami_model_receipt": metadata})
        + '\n\ndata: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, headers={"x-roami-model-call": CALL}, text=body)
        )
    ) as client:
        provider = ChatCompletions("https://fixture.invalid/v1", "fixture", client=client)
        events = [e async for e in provider.stream([], [])]
    assert not any(
        "gatewayCallId" in e.value or e.value.get("phase") == "upstream_headers"
        for e in events
        if e.kind == "telemetry"
    )


@pytest.mark.parametrize("status", [200, 401, 403, 503])
async def test_real_private_bridge_keeps_host_receipts_before_stream_failure(tmp_path, status):
    async with go_response(tmp_path, [(status, CALL)]) as (socket, calls):
        async with httpx.AsyncClient(
            transport=LocalGatewayTransport(str(socket), "worker")
        ) as host_client:
            host = ChatCompletions(
                "http://localhost/v1", "saved-fixture", client=host_client, max_retries=0
            )
            relay = tmp_path / "relay.sock"
            async with ModelGateway(relay, {"worker": host}) as gateway:
                async with httpx.AsyncClient(
                    transport=PrivateModelBridgeTransport(str(relay))
                ) as client:
                    actor = ChatCompletions(
                        "http://localhost/v1/worker", "worker", client=client, max_retries=0
                    )
                    events = []
                    if status == 200:
                        events = [e async for e in actor.stream([], [])]
                    else:
                        with pytest.raises(DomainError, match=f"MODEL_HTTP_{status}"):
                            async for e in actor.stream([], []):
                                events.append(e)
                assert gateway.errors == ([] if status == 200 else [f"MODEL_HTTP_{status}"])
        assert len(calls) == 1
    local = next(e.value for e in events if e.kind == "telemetry" and e.value["phase"] == "headers")
    remote = next(
        e.value for e in events if e.kind == "telemetry" and e.value["phase"] == "upstream_headers"
    )
    assert local["httpStatus"] == 200 and "gatewayCallId" not in local
    assert remote == {
        "phase": "upstream_headers",
        "attempt": 1,
        "upstreamAttempt": 1,
        "httpStatus": status,
        "gatewayCallId": CALL,
        "requestId": "upstream-1",
    }
    assert not any(e.kind in {"text", "tool"} for e in events)
    if status != 200:
        assert not any(e.kind == "usage" for e in events)


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {"phase": "usage", "attempt": 1},
        {"phase": "headers", "attempt": True},
        {"phase": "headers", "attempt": 0},
    ],
)
def test_invalid_receipts_are_not_relayed(value):
    assert forwarded_receipt(value) is None


async def test_bridge_drops_private_fields_and_never_turns_receipt_into_usage(tmp_path):
    class Provider:
        async def stream(self, messages, tools):
            yield ModelEvent(
                "telemetry",
                {
                    "phase": "headers",
                    "attempt": 1,
                    "gatewayCallId": "private invalid value",
                    "requestId": "<private>",
                    "httpStatus": True,
                    "authorization": "never relay",
                    "usage": {"inputTokens": 0},
                },
            )
            raise DomainError("MODEL_HTTP_401")

    relay = tmp_path / "relay.sock"
    async with (
        ModelGateway(relay, {"worker": Provider()}),
        httpx.AsyncClient(transport=PrivateModelBridgeTransport(str(relay))) as client,
    ):
        provider = ChatCompletions("http://localhost/v1/worker", "worker", client=client)
        events = []
        with pytest.raises(DomainError, match="MODEL_HTTP_401"):
            async for event in provider.stream([], []):
                events.append(event)
    receipt = next(
        e.value for e in events if e.kind == "telemetry" and e.value["phase"] == "upstream_headers"
    )
    assert receipt == {"phase": "upstream_headers", "attempt": 1, "upstreamAttempt": 1}
    assert "never relay" not in json.dumps([e.value for e in events])
    assert not any(e.kind == "usage" for e in events)


async def test_private_error_body_remains_unread_even_with_receipt_headers():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(401, stream=PrivateBody(), headers={"x-request-id": "safe-id"})
        )
    ) as client:
        provider = ChatCompletions("https://fixture.invalid/v1", "fixture", client=client)
        events = []
        with pytest.raises(DomainError, match="MODEL_HTTP_401"):
            async for event in provider.stream([], []):
                events.append(event)
    assert any(e.kind == "telemetry" and e.value.get("requestId") == "safe-id" for e in events)


async def test_host_retry_receipts_and_unknown_usage_survive_the_real_bridge(tmp_path):
    ids = [CALL, "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"]
    async with go_response(tmp_path, [(503, ids[0]), (503, ids[1]), (200, ids[2])]) as (
        socket,
        calls,
    ):
        async with httpx.AsyncClient(
            transport=LocalGatewayTransport(str(socket), "worker")
        ) as host_client:
            host = ChatCompletions(
                "http://localhost/v1", "saved-fixture", client=host_client, max_retries=2
            )
            relay = tmp_path / "relay.sock"
            async with (
                ModelGateway(relay, {"worker": host}),
                httpx.AsyncClient(transport=PrivateModelBridgeTransport(str(relay))) as client,
            ):
                actor = ChatCompletions(
                    "http://localhost/v1/worker", "worker", client=client, max_retries=0
                )
                observation = EpisodeBudget({})
                measured = MeteredModel(actor, observation, "worker")
                events = [e async for e in measured.stream([], [])]
        assert len(calls) == 3
    receipts = [
        e.value for e in events if e.kind == "telemetry" and e.value["phase"] == "upstream_headers"
    ]
    assert [r["gatewayCallId"] for r in receipts] == ids
    assert [r["httpStatus"] for r in receipts] == [503, 503, 200]
    assert [r["upstreamAttempt"] for r in receipts] == [1, 2, 3]
    usage = next(e.value for e in events if e.kind == "usage")
    assert usage["requestAttempts"] == 3 and usage["retryUsageKnown"] is False
    assert usage["inputTokens"] == 9 and usage["outputTokens"] == 2
    metrics = observation.metrics()
    assert metrics["tokens"] is None and metrics["observed_tokens"] == 11
    assert metrics["token_coverage"] == "unknown"


async def test_external_provider_cannot_claim_host_retry_accounting():
    data = {
        "choices": [{"delta": {}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 9, "completion_tokens": 2},
        "roami_model_metering": {"requestAttempts": 9, "retryUsageKnown": False},
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, text="data: " + json.dumps(data) + "\n\ndata: [DONE]\n\n")
        )
    ) as client:
        provider = ChatCompletions("https://fixture.invalid/v1", "fixture", client=client)
        events = [e async for e in provider.stream([], [])]
    usage = next(e.value for e in events if e.kind == "usage")
    assert usage["requestAttempts"] == 1 and usage["retryUsageKnown"] is True


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        {"requestAttempts": True, "retryUsageKnown": True},
        {"requestAttempts": 2, "retryUsageKnown": "true"},
        {"requestAttempts": 0, "retryUsageKnown": True},
    ],
)
async def test_invalid_private_usage_receipt_does_not_fabricate_complete_usage(tmp_path, metadata):
    class Provider:
        async def stream(self, messages, tools):
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 9,
                    "outputTokens": 2,
                    **(metadata or {"requestAttempts": None, "retryUsageKnown": None}),
                },
            )

    relay = tmp_path / "relay.sock"
    async with (
        ModelGateway(relay, {"worker": Provider()}),
        httpx.AsyncClient(transport=PrivateModelBridgeTransport(str(relay))) as client,
    ):
        provider = ChatCompletions("http://localhost/v1/worker", "worker", client=client)
        events = []
        with pytest.raises(DomainError, match="MODEL_USAGE_INVALID"):
            async for e in provider.stream([], []):
                events.append(e)
    assert not any(e.kind == "usage" for e in events)


async def test_interrupted_relay_attempt_keeps_unknown_total_attempt_count():
    from roami_agent.providers.request_receipts import BRIDGE_EXTENSION

    calls = []

    class Broken(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise httpx.ReadError("owned fixture connection interrupted")
            yield

    data = {
        "choices": [{"delta": {}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 9, "completion_tokens": 2},
        "roami_model_metering": {"requestAttempts": 2, "retryUsageKnown": True},
    }

    def response(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, stream=Broken(), extensions={BRIDGE_EXTENSION: True})
        return httpx.Response(
            200,
            text="data: " + json.dumps(data) + "\n\ndata: [DONE]\n\n",
            extensions={BRIDGE_EXTENSION: True},
        )

    async def sleep(delay):
        pass

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        provider = ChatCompletions(
            "http://localhost/v1/worker", "worker", client=client, max_retries=1, sleep=sleep
        )
        events = [e async for e in provider.stream([], [])]
    assert len(calls) == 2
    usage = next(e.value for e in events if e.kind == "usage")
    assert usage["requestAttempts"] is None and usage["retryUsageKnown"] is False


async def test_actual_agent_failure_trace_keeps_go_call_receipt(store, tmp_path):
    from test_runtime import until

    from roami_agent.app import Runtime
    from roami_agent.server.configuration import Settings
    from roami_agent.storage.database import row

    async with go_response(tmp_path, [(401, CALL)]) as (socket, calls):
        client = httpx.AsyncClient(transport=LocalGatewayTransport(str(socket), "main"))
        provider = ChatCompletions("http://localhost/v1", "fixture", client=client)
        runtime = Runtime(store, provider, settings=Settings(workers=0))
        await runtime.start()
        try:
            conversation = await runtime.conversations.create("alice")
            receipt = await runtime.chat.submit(
                "alice", conversation["id"], "failure-receipt", "Inspect the current state"
            )
            await until(
                store,
                lambda db: row(
                    db, 'SELECT id FROM turns WHERE id=? AND state="failed"', (receipt["turnId"],)
                ),
            )
            trace = await runtime.traces.get("alice", turn_id=receipt["turnId"])
            model = next(s for s in trace["spans"] if s["name"] == "model.request")
            headers = next(
                x for x in model["attributes"]["providerEvents"] if x["phase"] == "headers"
            )
            assert headers["gatewayCallId"] == CALL and headers["httpStatus"] == 401
            assert trace["summary"]["hasFailures"] and len(calls) == 1
        finally:
            await runtime.close()
