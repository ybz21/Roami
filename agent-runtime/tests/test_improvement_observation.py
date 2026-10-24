import httpx
import pytest

from roami_agent.improvement.measurements import EpisodeBudget, MeteredModel
from roami_agent.protocol.model_observation import model_observation
from roami_agent.providers.chat_completions import ChatCompletions


@pytest.mark.asyncio
async def test_evaluator_identity_is_reconcilable_and_never_leaks_to_normal_requests():
    seen = []

    def respond(request):
        seen.append(dict(request.headers))
        return httpx.Response(
            200,
            headers={"x-request-id": "provider-receipt-1"},
            content=(
                'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
                'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":2}}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = ChatCompletions(
            "https://fixture.invalid/v1", "fixture", client=client, max_retries=0
        )
        journal = []
        budget = EpisodeBudget(
            {"tokens": 10000, "seconds": 10, "requests": 1}, observation_id="rsi-test-run"
        )
        model = MeteredModel(provider, budget, "memory", journal=journal)
        assert [
            e.value
            async for e in model.stream([{"role": "user", "content": "test"}], [])
            if e.kind == "text"
        ] == ["ok"]
        assert model_observation.get() is None
        async for _event in provider.stream([{"role": "user", "content": "normal"}], []):
            pass
    assert seen[0]["x-eval-session-id"] == "rsi-test-run"
    assert seen[0]["x-request-id"] == journal[0]["request_id"]
    assert "x-eval-session-id" not in seen[1] and "x-request-id" not in seen[1]
    assert journal[0]["model"] == "fixture"
    assert any(
        e["value"].get("requestId") == "provider-receipt-1"
        for e in journal[0]["events"]
        if e["kind"] == "telemetry"
    )
    assert budget.metrics()["tokens"] == 14


@pytest.mark.asyncio
async def test_nested_meters_share_one_upstream_request_identity():
    from roami_agent.protocol.models import ModelEvent

    class Provider:
        model = "fixture"

        async def stream(self, messages, tools):
            assert model_observation.get()["role"] == "worker"
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 1,
                    "outputTokens": 1,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )

    inner_journal, outer_journal = [], []
    inner = MeteredModel(
        Provider(),
        EpisodeBudget({"tokens": 10000, "seconds": 10, "requests": 1}),
        "worker",
        journal=inner_journal,
    )
    outer = MeteredModel(
        inner,
        EpisodeBudget({"tokens": 10000, "seconds": 10, "requests": 1}),
        "worker",
        journal=outer_journal,
    )
    async for _ in outer.stream([], []):
        pass
    assert inner_journal[0]["request_id"] == outer_journal[0]["request_id"]
    assert model_observation.get() is None
