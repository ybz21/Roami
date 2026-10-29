"""Failure receipts keep safe upstream IDs without reading private error bodies."""

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
        {"phase": "headers", "attempt": 1, "requestId": f"trace-{status}"}
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
        {"phase": "headers", "attempt": 1}
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
