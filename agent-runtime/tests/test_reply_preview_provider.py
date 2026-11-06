"""Provider argument deltas precede tool completion and are independent snapshots."""

import json

import httpx

from roami_agent.providers.chat_completions import ChatCompletions


async def test_chat_completions_exposes_tool_argument_stream_without_early_tool_execution():
    fragments = [
        {"index": 0, "id": "reply-call", "function": {"name": "re", "arguments": ""}},
        {"index": 0, "function": {"name": "ply", "arguments": '{"text":"First'}},
        {"index": 0, "function": {"arguments": ' second"}'}},
    ]
    frames = [{"choices": [{"delta": {"tool_calls": [part]}}]} for part in fragments]
    frames.append({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]})
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, text="".join("data: " + json.dumps(frame) + "\n\n" for frame in frames)
            )
        )
    ) as client:
        model = ChatCompletions("https://fixture.invalid/v1", "fixture", client=client)
        events = [part async for part in model.stream([], [])]
    partials = [event.value for event in events if event.kind == "tool_delta"]
    assert [value["name"] for value in partials] == ["re", "reply", "reply"]
    assert [value["arguments"] for value in partials] == [
        "",
        '{"text":"First',
        '{"text":"First second"}',
    ]
    assert len([event for event in events if event.kind == "tool"]) == 1
    assert next(i for i, event in enumerate(events) if event.kind == "tool") > max(
        i for i, event in enumerate(events) if event.kind == "tool_delta"
    )


async def test_partial_arguments_preserve_safe_transport_retries_without_executing_old_tools():
    from unittest.mock import AsyncMock

    requests = []

    class BrokenBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"old","function":{"name":"reply","arguments":"{\\"text\\":\\"Old"}}]}}]}\n\n'
            raise httpx.ReadError("fixture disconnect")

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, stream=BrokenBody())
        event = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "fresh",
                                "function": {"name": "reply", "arguments": '{"text":"Fresh"}'},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
        return httpx.Response(200, text="data: " + json.dumps(event) + "\n\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = ChatCompletions(
            "https://fixture.invalid/v1", "fixture", client=client, max_retries=1, sleep=AsyncMock()
        )
        events = [event async for event in model.stream([], [])]
    assert len(requests) == 2
    assert [event.value["id"] for event in events if event.kind == "tool"] == ["fresh"]
    assert (
        len(
            [
                event
                for event in events
                if event.kind == "telemetry" and event.value.get("phase") == "retry"
            ]
        )
        == 1
    )
    assert [event.value["arguments"] for event in events if event.kind == "tool_delta"] == [
        '{"text":"Old',
        '{"text":"Fresh"}',
    ]
