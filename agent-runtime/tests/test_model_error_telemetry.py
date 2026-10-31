"""Failure receipts keep safe upstream IDs without reading private error bodies."""

import json
from pathlib import Path

import httpx
import pytest

from roami_agent.protocol.errors import DomainError
from roami_agent.providers.chat_completions import ChatCompletions


class PrivateBody(httpx.AsyncByteStream):
    async def __aiter__(self):
        raise AssertionError("Error bodies must not be read")
        yield


@pytest.mark.parametrize("status", [401, 403, 429, 503, 302])
async def test_http_failures_record_request_id_before_raising(status):
    events, calls = [], []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            status, headers={"x-request-id": f"trace-{status}"}, stream=PrivateBody()
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = ChatCompletions(
            "https://fixture.invalid/v1", "fixture", max_retries=0, client=client
        )
        with pytest.raises(DomainError) as caught:
            async for event in provider.stream([], []):
                events.append(event)
    assert caught.value.code == (
        "MODEL_REDIRECT_BLOCKED" if status == 302 else f"MODEL_HTTP_{status}"
    )
    assert caught.value.status == 502 and len(calls) == 1
    assert [e.value for e in events if e.kind == "telemetry" and e.value["phase"] == "headers"] == [
        {"phase": "headers", "attempt": 1, "httpStatus": status, "requestId": f"trace-{status}"}
    ]
    assert not any(e.kind in {"text", "tool", "usage"} for e in events)


@pytest.mark.parametrize("request_id", ["private detail with spaces", "x" * 201, "<private>"])
async def test_failed_request_ids_keep_existing_sanitization(request_id):
    events = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                401, headers={"request-id": request_id}, stream=PrivateBody()
            )
        )
    ) as client:
        provider = ChatCompletions("https://fixture.invalid/v1", "fixture", client=client)
        with pytest.raises(DomainError, match="MODEL_HTTP_401"):
            async for event in provider.stream([], []):
                events.append(event)
    assert [e.value for e in events if e.kind == "telemetry" and e.value["phase"] == "headers"] == [
        {"phase": "headers", "attempt": 1, "httpStatus": 401}
    ]


async def test_error_headers_do_not_disable_configured_retries_or_invent_retry_usage():
    calls, delays, events = [], [], []

    def respond(request):
        calls.append(request)
        headers = {"request-id": f"attempt-{len(calls)}", "Retry-After": "0"}
        if len(calls) < 3:
            return httpx.Response(503, headers=headers, stream=PrivateBody())
        return httpx.Response(
            200,
            headers=headers,
            text='data: {"usage":{"prompt_tokens":21,"completion_tokens":4},"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
        )

    async def sleep(delay):
        delays.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = ChatCompletions(
            "https://fixture.invalid/v1", "fixture", client=client, max_retries=2, sleep=sleep
        )
        async for event in provider.stream([], []):
            events.append(event)
    assert len(calls) == 3 and len(delays) == 2
    receipts = [e.value for e in events if e.kind == "telemetry" and e.value["phase"] == "headers"]
    assert [(r["attempt"], r["requestId"]) for r in receipts] == [
        (1, "attempt-1"),
        (2, "attempt-2"),
        (3, "attempt-3"),
    ]
    usage = next(e.value for e in events if e.kind == "usage")
    assert usage["inputTokens"] == 21 and usage["outputTokens"] == 4
    assert usage["requestAttempts"] == 3 and usage["retryUsageKnown"] is False


TRANSPORT_FAILURES = json.loads(
    (Path(__file__).parent / "fixtures/model-transport-failures.json").read_text()
)
TRANSPORT_ERRORS = {
    "connect_error": httpx.ConnectError,
    "connect_timeout": httpx.ConnectTimeout,
    "read_error": httpx.ReadError,
    "read_timeout": httpx.ReadTimeout,
    "protocol_error": httpx.RemoteProtocolError,
    "write_error": httpx.WriteError,
    "write_timeout": httpx.WriteTimeout,
    "pool_timeout": httpx.PoolTimeout,
}


@pytest.mark.parametrize("item", TRANSPORT_FAILURES, ids=lambda i: i["kind"] + "-" + i["stage"])
async def test_transport_failure_retains_safe_stage_and_type(item):
    events, calls = [], []
    private = "https://private.invalid/path?credential=do-not-disclose"

    class Broken(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b": heartbeat\n\n"
            raise TRANSPORT_ERRORS[item["kind"]](private)

    def respond(request):
        calls.append(request)
        if item["response_started"]:
            return httpx.Response(200, stream=Broken())
        raise TRANSPORT_ERRORS[item["kind"]](private, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = ChatCompletions(
            "https://fixture.invalid/v1", "fixture", max_retries=0, client=client
        )
        with pytest.raises(DomainError, match="^MODEL_TRANSPORT_FAILED$"):
            async for event in provider.stream([], []):
                events.append(event)
    failure = next(
        e.value for e in events if e.kind == "telemetry" and e.value["phase"] == "transport_error"
    )
    assert failure == {
        "phase": "transport_error",
        "attempt": 1,
        "errorCode": "MODEL_TRANSPORT_FAILED",
        "failureStage": item["stage"],
        "failureType": item["kind"],
    }
    assert len(calls) == 1 and private not in json.dumps([e.value for e in events])
    assert not any(e.kind in {"text", "tool", "usage"} for e in events)


async def test_retry_evidence_keeps_configured_attempts_and_unknown_usage():
    calls, delays, events = [], [], []

    def respond(request):
        calls.append(request)
        if len(calls) < 3:
            raise httpx.ConnectError("private transport detail", request=request)
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":11,"completion_tokens":2}}\n\ndata: [DONE]\n\n',
        )

    async def sleep(delay):
        delays.append(delay)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = ChatCompletions(
            "https://fixture.invalid/v1", "fixture", max_retries=2, sleep=sleep, client=client
        )
        events = [e async for e in provider.stream([], [])]
    retries = [e.value for e in events if e.kind == "telemetry" and e.value["phase"] == "retry"]
    assert len(calls) == 3 and delays == [0.25, 0.5]
    assert [(e["attempt"], e["failureStage"], e["failureType"]) for e in retries] == [
        (1, "connect", "connect_error"),
        (2, "connect", "connect_error"),
    ]
    assert not any(e.kind == "telemetry" and e.value["phase"] == "transport_error" for e in events)
    usage = next(e.value for e in events if e.kind == "usage")
    assert usage["requestAttempts"] == 3 and usage["retryUsageKnown"] is False


async def test_actual_runtime_persists_transport_failure_evidence(store):
    from test_runtime import until

    from roami_agent.app import Runtime
    from roami_agent.server.configuration import Settings
    from roami_agent.storage.database import row

    class Broken(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b": heartbeat\n\n"
            raise httpx.ReadTimeout("private stream diagnostics")

    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200, headers={"x-request-id": "fixture-read-timeout"}, stream=Broken()
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    provider = ChatCompletions(
        "https://fixture.invalid/v1", "fixture", max_retries=0, client=client
    )
    runtime = Runtime(store, provider, settings=Settings(workers=0))
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        submitted = await runtime.chat.submit(
            "alice", conversation["id"], "transport-trace", "Inspect the current state"
        )
        await until(
            store,
            lambda db: row(
                db, 'SELECT id FROM turns WHERE id=? AND state="failed"', (submitted["turnId"],)
            ),
        )
        trace = await runtime.traces.get("alice", turn_id=submitted["turnId"])
        span = next(s for s in trace["spans"] if s["name"] == "model.request")
        facts = span["attributes"]["providerEvents"]
        failure = next(e for e in facts if e["phase"] == "transport_error")
        assert (
            failure["failureStage"] == "response_body" and failure["failureType"] == "read_timeout"
        )
        assert (
            next(e for e in facts if e["phase"] == "headers")["requestId"] == "fixture-read-timeout"
        )
        assert span["attributes"]["errorCode"] == "MODEL_TRANSPORT_FAILED"
        assert trace["summary"]["hasFailures"] and len(calls) == 1
        assert "private stream diagnostics" not in json.dumps(trace)
    finally:
        await runtime.close()


@pytest.mark.parametrize("code", ["MODEL_TRANSPORT_FAILED", "MODEL_RETRY_DEADLINE"])
async def test_private_relay_keeps_safe_failure_facts_and_terminal_code(tmp_path, code):
    from roami_agent.improvement.integrations.model_gateway import ModelGateway
    from roami_agent.protocol.models import ModelEvent
    from roami_agent.providers.model_bridge_transport import PrivateModelBridgeTransport

    class Provider:
        async def stream(self, messages, tools):
            yield ModelEvent(
                "telemetry",
                {
                    "phase": "transport_error",
                    "attempt": 2,
                    "errorCode": code,
                    "failureType": "read_timeout",
                    "failureStage": "response_body",
                    "private": "do-not-forward",
                },
            )
            raise DomainError(code)

    socket = tmp_path / "relay.sock"
    async with (
        ModelGateway(socket, {"worker": Provider()}),
        httpx.AsyncClient(transport=PrivateModelBridgeTransport(str(socket))) as client,
    ):
        model = ChatCompletions(
            "http://localhost/v1/worker", "fixture", max_retries=0, client=client
        )
        events = []
        with pytest.raises(DomainError, match="^" + code + "$"):
            async for e in model.stream([], []):
                events.append(e)
    facts = next(
        e.value
        for e in events
        if e.kind == "telemetry" and e.value["phase"] == "upstream_transport_error"
    )
    assert facts == {
        "phase": "upstream_transport_error",
        "attempt": 1,
        "upstreamAttempt": 2,
        "errorCode": code,
        "failureType": "read_timeout",
        "failureStage": "response_body",
    }
    assert "do-not-forward" not in json.dumps([e.value for e in events])


@pytest.mark.parametrize("trusted", [False, True])
async def test_transport_wire_extension_needs_private_bridge_and_valid_fields(trusted):
    from roami_agent.providers.request_receipts import BRIDGE_EXTENSION

    facts = {
        "phase": "transport_error",
        "attempt": 1,
        "errorCode": "MODEL_TRANSPORT_FAILED",
        "failureType": "read_error",
        "failureStage": "response_body",
    }
    frames = [
        {"choices": [], "roami_model_transport": facts},
        *[
            {"choices": [], "roami_model_transport": {**facts, **invalid}}
            for invalid in [
                {"phase": []},
                {"errorCode": {}},
                {"attempt": True},
                {"failureStage": "private"},
                {"failureType": "connect_error"},
            ]
        ],
        {
            "choices": [],
            "roami_model_transport": {**facts, "failureType": "https://private.invalid"},
        },
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]

    def respond(request):
        return httpx.Response(
            200,
            text="".join("data: " + json.dumps(f) + "\n\n" for f in frames) + "data: [DONE]\n\n",
            extensions={BRIDGE_EXTENSION: trusted},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = ChatCompletions("https://fixture.invalid/v1", "fixture", client=client)
        events = [e async for e in model.stream([], [])]
    failures = [
        e.value
        for e in events
        if e.kind == "telemetry" and e.value["phase"] == "upstream_transport_error"
    ]
    assert len(failures) == (1 if trusted else 0)
    assert "private.invalid" not in json.dumps([e.value for e in events])


async def test_actual_runtime_keeps_upstream_failure_through_private_relay(store, tmp_path):
    from test_runtime import until

    from roami_agent.app import Runtime
    from roami_agent.improvement.integrations.model_gateway import ModelGateway
    from roami_agent.providers.model_bridge_transport import PrivateModelBridgeTransport
    from roami_agent.server.configuration import Settings
    from roami_agent.storage.database import row

    class Broken(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b": heartbeat\n\n"
            raise httpx.ReadTimeout("private host failure")

    def respond(request):
        return httpx.Response(200, headers={"x-request-id": "host-stream-failure"}, stream=Broken())

    host = ChatCompletions(
        "https://fixture.invalid/v1",
        "fixture",
        max_retries=0,
        client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    socket = tmp_path / "model.sock"
    try:
        async with ModelGateway(socket, {"main": host}):
            child = ChatCompletions(
                "http://localhost/v1/main",
                "fixture",
                max_retries=0,
                client=httpx.AsyncClient(transport=PrivateModelBridgeTransport(str(socket))),
            )
            runtime = Runtime(store, child, settings=Settings(workers=0))
            await runtime.start()
            try:
                conversation = await runtime.conversations.create("alice")
                submitted = await runtime.chat.submit(
                    "alice",
                    conversation["id"],
                    "relay-transport-trace",
                    "Inspect the current state",
                )
                await until(
                    store,
                    lambda db: row(
                        db,
                        'SELECT id FROM turns WHERE id=? AND state="failed"',
                        (submitted["turnId"],),
                    ),
                )
                trace = await runtime.traces.get("alice", turn_id=submitted["turnId"])
                span = next(s for s in trace["spans"] if s["name"] == "model.request")
                facts = span["attributes"]["providerEvents"]
                error = next(e for e in facts if e["phase"] == "upstream_transport_error")
                assert (
                    error["failureStage"] == "response_body"
                    and error["failureType"] == "read_timeout"
                )
                assert error["upstreamAttempt"] == 1 and error["attempt"] == 1
                assert (
                    next(e for e in facts if e["phase"] == "upstream_headers")["requestId"]
                    == "host-stream-failure"
                )
                assert (
                    span["attributes"]["errorCode"] == "MODEL_TRANSPORT_FAILED"
                    and trace["summary"]["hasFailures"]
                )
                assert "private host failure" not in json.dumps(trace)
            finally:
                await runtime.close()
    finally:
        await host.close()
