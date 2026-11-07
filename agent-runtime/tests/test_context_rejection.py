"""Private provider errors may reduce summary fragments, never escape as diagnostics."""

import asyncio

import httpx
import pytest

from roami_agent.protocol.errors import DomainError
from roami_agent.providers.chat_completions import ChatCompletions


@pytest.mark.parametrize(
    "body,expected",
    [
        ({"error": {"code": "context_length_exceeded", "message": "private-secret"}}, True),
        (
            {
                "error": {
                    "message": "Input length 1500000 exceeds the context length 1048568 tokens."
                }
            },
            True,
        ),
        (
            {
                "error": {
                    "message": "This model's maximum context length is 4096 tokens. However, you requested 5000 tokens."
                }
            },
            True,
        ),
        ({"message": "Input is too long for the context window. private-secret"}, True),
        ({"error": {"message": "Invalid temperature; context length is 4096 tokens."}}, False),
        ({"error": {"message": "Input length is 500, maximum context length 4096 tokens."}}, False),
        (
            {
                "error": {
                    "message": "Invalid temperature; echoed prompt: Input exceeds context length."
                }
            },
            False,
        ),
        ({"error": {"code": ["context_length_exceeded"]}}, False),
        ({"error": "private-secret: context_length_exceeded"}, False),
        ([{"error": {"code": "context_length_exceeded"}}], False),
        ({"error": {"code": "context_length_exceeded", "message": "private-secret" * 2000}}, False),
    ],
)
async def test_context_rejection_is_specific_bounded_and_never_leaks(body, expected):
    calls, events = [], []

    async def handle(request):
        calls.append(request)
        return httpx.Response(400, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        model = ChatCompletions("https://provider.invalid/v1", "saved-model", client=client)
        code = "MODEL_CONTEXT_LIMIT" if expected else "MODEL_HTTP_400"
        with pytest.raises(DomainError, match="^" + code + "$"):
            async for item in model.stream([], []):
                events.append(item)
    assert len(calls) == 1
    assert "private-secret" not in repr(events)
    assert not any(item.kind in {"text", "tool", "tool_delta"} for item in events)


async def test_stalled_error_body_does_not_delay_or_retry_the_known_400_forever():
    class Stalled(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.Event().wait()
            yield b""

    calls = []

    async def handle(request):
        calls.append(request)
        return httpx.Response(400, stream=Stalled())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        model = ChatCompletions("https://provider.invalid/v1", "saved-model", client=client)
        async with asyncio.timeout(5):
            with pytest.raises(DomainError, match="^MODEL_HTTP_400$"):
                _ = [item async for item in model.stream([], [])]
    assert len(calls) == 1


async def test_unreadable_400_body_keeps_the_original_nonretryable_status():
    class Broken(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"error":'
            raise httpx.ReadError("private-secret")

    calls = []

    async def handle(request):
        calls.append(request)
        return httpx.Response(400, stream=Broken())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        model = ChatCompletions("https://provider.invalid/v1", "saved-model", client=client)
        with pytest.raises(DomainError, match="^MODEL_HTTP_400$"):
            _ = [item async for item in model.stream([], [])]
    assert len(calls) == 1
