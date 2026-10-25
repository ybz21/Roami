from dataclasses import replace

import pytest

from roami_agent.improvement.measurements import (
    BudgetAdmissionRejected,
    EpisodeBudget,
    MeteredModel,
)
from roami_agent.improvement.request_model import RequestBudgetModel
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "configured,explicit,expected",
    [(32768, None, 32768), (32768, 16384, 16384), (None, None, None)],
)
async def test_output_uses_model_role_and_remaining_budget(configured, explicit, expected):
    settings = Settings()
    route = settings.route("worker")
    route = replace(route, parameters={"max_tokens": configured} if configured else {})
    caps = []

    class Provider:
        model = "fixture"

        async def stream(self, messages, tools):
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 10,
                    "outputTokens": 2,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )

        async def close(self):
            pass

    def factory(settings, role):
        caps.append(settings.route("worker").parameters["max_tokens"])
        return Provider()

    budget = EpisodeBudget({"tokens": 100000, "seconds": 10, "requests": 2})
    journal = []
    model = RequestBudgetModel(
        settings, route, budget, "worker", cap=explicit, factory=factory, journal=journal
    )
    for _ in range(2):
        async for _ in model.stream([], []):
            pass
    assert caps[0] == expected if expected else caps[0] > 8192
    assert caps[1] <= caps[0]
    assert journal[0]["output_cap"] == caps[0]
    assert budget.used == 24


@pytest.mark.asyncio
async def test_unfunded_request_never_calls_provider_and_model_limit_is_respected():
    settings = Settings()
    route = replace(settings.route("worker"), capabilities={"max_output_tokens": 1000})
    caps = []

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

    def factory(settings, role):
        caps.append(settings.route("worker").parameters["max_tokens"])
        return Provider()

    budget = EpisodeBudget({"tokens": 20000, "seconds": 10, "requests": 1})
    model = RequestBudgetModel(settings, route, budget, "worker", factory=factory)
    async for _ in model.stream([], []):
        pass
    assert caps == [1000]
    with pytest.raises(BudgetAdmissionRejected):
        async for _ in model.stream([{"role": "user", "content": "x" * 20000}], []):
            pass
    assert caps == [1000] and not budget.unknown


@pytest.mark.asyncio
async def test_output_allocation_respects_shared_reservations_before_provider_admission():
    settings = Settings()
    case_budget = EpisodeBudget({"tokens": 100000, "seconds": 10, "requests": 4})
    run_budget = EpisodeBudget({"tokens": 20000, "seconds": 10, "requests": 4})
    held, reservation = await run_budget.admit([], [], 3000)
    caps, closed = [], []

    class Provider:
        model = "fixture"

        async def stream(self, messages, tools):
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 10,
                    "outputTokens": 2,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )

        async def close(self):
            closed.append(True)

    def factory(config, role):
        cap = config.route("worker").parameters["max_tokens"]
        caps.append(cap)
        return MeteredModel(Provider(), run_budget, role, output_cap=cap)

    model = RequestBudgetModel(
        settings,
        settings.route("worker"),
        case_budget,
        "worker",
        cap=32768,
        factory=factory,
        shared_budget=run_budget,
    )
    async for _ in model.stream([], []):
        pass
    assert 512 <= caps[0] < 10000
    assert case_budget.used == run_budget.used == 12
    assert case_budget.reserved == 0 and run_budget.reserved == reservation
    assert closed == [True]
    await run_budget.settle(
        held,
        reservation,
        {"inputTokens": 0, "outputTokens": 0, "requestAttempts": 0, "retryUsageKnown": True},
        0,
    )
    assert not case_budget.unknown and not run_budget.unknown


@pytest.mark.asyncio
async def test_context_capacity_and_unknown_shared_usage_block_before_factory():
    settings = Settings()
    route = replace(settings.route("worker"), context_window=4200)
    case_budget = EpisodeBudget({"tokens": 100000, "seconds": 10, "requests": 2})
    run_budget = EpisodeBudget({"tokens": 100000, "seconds": 10, "requests": 2})

    def forbidden(*args):
        raise AssertionError("unfunded requests must not create a provider")

    model = RequestBudgetModel(
        settings, route, case_budget, "worker", factory=forbidden, shared_budget=run_budget
    )
    with pytest.raises(BudgetAdmissionRejected, match="RSI_TOKEN_BUDGET"):
        async for _ in model.stream([], []):
            pass
    run_budget.unknown = True
    with pytest.raises(BudgetAdmissionRejected, match="RSI_USAGE_UNKNOWN"):
        async for _ in model.stream([], []):
            pass
    assert not case_budget.requests and not run_budget.requests
