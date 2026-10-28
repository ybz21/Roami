import json

import httpx
import pytest
from test_memory_pipeline import source
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.improvement.integrations.model_gateway import ModelGateway
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.providers.chat_completions import ChatCompletions
from roami_agent.storage.database import event, row


@pytest.mark.parametrize(
    "error,expected",
    [
        ({"code": "MODEL_OUTPUT_LENGTH"}, "MODEL_OUTPUT_LENGTH"),
        ({"code": "MODEL_OUTPUT_CONTENT_FILTER"}, "MODEL_OUTPUT_CONTENT_FILTER"),
        ({"code": "RSI_TOKEN_BUDGET"}, "RSI_TOKEN_BUDGET"),
        ({"code": "RSI_USAGE_UNKNOWN"}, "RSI_USAGE_UNKNOWN"),
        ({"code": "private-provider-detail"}, "MODEL_STREAM_INVALID"),
        ({"code": []}, "MODEL_STREAM_INVALID"),
        ("private-provider-detail", "MODEL_STREAM_INVALID"),
    ],
)
async def test_stream_errors_preserve_usage_without_retries_or_partial_tools(error, expected):
    requests = []

    def respond(request):
        requests.append(request)
        frames = [
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "partial",
                                    "function": {"name": "write", "arguments": "{}"},
                                }
                            ]
                        }
                    }
                ]
            },
            {"usage": {"prompt_tokens": 37, "completion_tokens": 5}, "error": error},
        ]
        return httpx.Response(200, text="".join("data: " + json.dumps(f) + "\n\n" for f in frames))

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = ChatCompletions(
            "https://fixture.invalid/v1", "fixture", client=client, max_retries=3
        )
        events = []
        with pytest.raises(DomainError, match=expected) as caught:
            async for item in model.stream([], []):
                events.append(item)
        assert caught.value.code == expected and "private-provider-detail" not in str(caught.value)
        assert len(requests) == 1 and not any(e.kind == "tool" for e in events)
        usage = next(e.value for e in events if e.kind == "usage")
        assert usage["inputTokens"] == 37 and usage["outputTokens"] == 5


@pytest.mark.parametrize(
    "code", ["MODEL_OUTPUT_LENGTH", "MODEL_OUTPUT_CONTENT_FILTER", "MODEL_IMAGES_UNSUPPORTED"]
)
async def test_gateway_memory_terminal_errors_do_not_become_retryable_stream_failures(
    store, tmp_path, code
):
    calls = []

    class Failed:
        async def stream(self, messages, tools):
            calls.append(True)
            yield ModelEvent("usage", {"inputTokens": 21, "outputTokens": 4})
            raise DomainError(code)

    c, receipt, _ = await source(store)
    await store.call(
        lambda db: event(db, c["id"], "message.completed", {}, message_id=receipt["messageId"]),
        write=True,
    )
    async with ModelGateway(tmp_path / "model.sock", {"memory": Failed()}) as gateway:
        provider = ChatCompletions(
            "http://localhost/v1/memory",
            "memory",
            max_retries=0,
            client=httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=str(tmp_path / "model.sock"))
            ),
        )
        runtime = Runtime(store, ConversationModel(), memory_model=provider)
        try:
            await runtime.memory_jobs.scan()
            job = await store.call(
                lambda db: row(db, "SELECT * FROM jobs WHERE kind='memory.extract'")
            )
            await runtime.memory_jobs.run(job)
            await runtime.memory_jobs.run(job)
            saved = await store.call(
                lambda db: row(db, "SELECT * FROM jobs WHERE id=?", (job["id"],))
            )
            payload = json.loads(saved["payload_json"])
            assert saved["state"] == "failed" and saved["attempts"] == 1 and len(calls) == 1
            assert payload["lastError"] == code and gateway.errors == [code]
            assert payload["usage"]["inputTokens"] == 21 and payload["usage"]["outputTokens"] == 4
        finally:
            await runtime.close()
            await provider.close()
