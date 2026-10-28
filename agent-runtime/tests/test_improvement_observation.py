import httpx
import pytest

from roami_agent.improvement.integrations.measurements import EpisodeBudget, MeteredModel
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


@pytest.mark.asyncio
async def test_closed_stream_is_not_an_invented_model_failure():
    from roami_agent.protocol.models import ModelEvent

    class Provider:
        model = "fixture"

        async def stream(self, messages, tools):
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 7,
                    "outputTokens": 1,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )
            yield ModelEvent("text", "unused")

    journal = []
    budget = EpisodeBudget({"tokens": 10000, "seconds": 10, "requests": 1})
    stream = MeteredModel(Provider(), budget, "worker", journal=journal).stream([], [])
    await anext(stream)
    await stream.aclose()
    assert journal[0]["termination"] == "closed"
    assert "error_code" not in journal[0]
    assert budget.metrics()["tokens"] == 8


@pytest.mark.asyncio
async def test_nested_admission_rejection_is_known_zero_and_never_reaches_provider():
    from roami_agent.protocol.errors import DomainError
    from roami_agent.protocol.models import ModelEvent

    class Provider:
        model = "fixture"

        async def stream(self, messages, tools):
            raise AssertionError("must not send a provider request")
            yield ModelEvent("text", "unused")

    outer_budget = EpisodeBudget({"tokens": 1, "seconds": 10, "requests": 1})
    inner_budget = EpisodeBudget({"tokens": 10000, "seconds": 10, "requests": 1})
    journal = []
    model = MeteredModel(
        MeteredModel(Provider(), outer_budget, "worker"), inner_budget, "worker", journal=journal
    )
    with pytest.raises(DomainError, match="RSI_TOKEN_BUDGET"):
        async for _ in model.stream([], []):
            pass
    assert not inner_budget.unknown and not outer_budget.unknown
    assert journal[0]["admission_rejected"] is True
    assert inner_budget.metrics()["tokens"] == 0
    assert inner_budget.metrics()["request_attempts"] == 0


@pytest.mark.asyncio
async def test_stream_closed_by_another_task_does_not_leak_context():
    import asyncio

    from roami_agent.protocol.models import ModelEvent

    class Provider:
        model = "fixture"

        async def stream(self, messages, tools):
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 1,
                    "outputTokens": 1,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )
            yield ModelEvent("text", "unused")

    budget = EpisodeBudget({"tokens": 10000, "seconds": 10, "requests": 1})
    stream = MeteredModel(Provider(), budget, "worker").stream([], [])
    await anext(stream)
    assert model_observation.get() is None
    await asyncio.create_task(stream.aclose())
    assert budget.metrics()["tokens"] == 2
    assert model_observation.get() is None
