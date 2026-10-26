import asyncio
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


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["main", "worker", "memory"])
async def test_budget_status_uses_shared_allowance_without_mutating_history(role):
    settings = Settings()
    case = EpisodeBudget({"tokens": 100000, "seconds": 10, "requests": 3})
    shared = EpisodeBudget({"tokens": 20000, "seconds": 10, "requests": 3})
    shared.used = 12000
    original = [{"role": "user", "content": "Keep the supplied task unchanged."}]
    received = []

    class Provider:
        model = "fixture"

        async def stream(self, messages, tools):
            received.append(messages)
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 100,
                    "outputTokens": 20,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )

    model = RequestBudgetModel(
        settings,
        settings.route("worker"),
        case,
        role,
        factory=lambda *_: Provider(),
        shared_budget=shared,
    )
    async for _ in model.stream(original, []):
        pass
    assert len(original) == 1 and received[0][0] == original[0]
    if role == "memory":
        assert received[0] == original
    else:
        assert received[0][-1]["role"] == "system"
        assert "8000 metered tokens remain" in received[0][-1]["content"]
        assert "Budget pressure" in received[0][-1]["content"]
    assert case.used == 120 and case.reserved == 0 and not case.unknown


@pytest.mark.asyncio
async def test_budget_notice_is_funded_before_provider_creation():
    settings = Settings()
    calls = []

    def forbidden(*args):
        calls.append(args)
        raise AssertionError("notice must fit before provider creation")

    budget = EpisodeBudget({"tokens": 5500, "seconds": 10, "requests": 1})
    model = RequestBudgetModel(
        settings, settings.route("worker"), budget, "worker", factory=forbidden
    )
    with pytest.raises(BudgetAdmissionRejected, match="RSI_TOKEN_BUDGET"):
        async for _ in model.stream([], []):
            pass
    assert not calls and not budget.requests and not budget.unknown


async def prefix_model():
    settings = Settings()
    case = EpisodeBudget({"tokens": 30000, "seconds": 30, "requests": 6})
    shared = EpisodeBudget({"tokens": 30000, "seconds": 30, "requests": 6})
    calls, journal, run_journal = [], [], []

    class Provider:
        model = "prefix-fixture"

        async def stream(self, messages, tools):
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 2000 + 300 * (len(calls) - 1),
                    "outputTokens": 100,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )

    def factory(config, role):
        calls.append(config.route("worker").parameters["max_tokens"])
        return MeteredModel(Provider(), shared, role, output_cap=calls[-1], journal=run_journal)

    model = RequestBudgetModel(
        settings,
        settings.route("worker"),
        case,
        "worker",
        cap=1024,
        factory=factory,
        shared_budget=shared,
        journal=journal,
    )
    original = [{"role": "user", "content": "x" * 12000}]
    async for _ in model.stream(original, []):
        pass
    held, reservation = await shared.admit([], [], 12000)
    return model, case, shared, calls, journal, run_journal, original, held, reservation


async def test_known_text_prefix_funds_both_budgets_without_discounting_usage():
    model, case, shared, calls, journal, run_log, original, held, reservation = await prefix_model()
    grown = original + [
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "continue"},
    ]
    async for _ in model.stream(grown, []):
        pass
    assert len(calls) == 2 and case.used == shared.used == 4500
    assert case.reserved == 0 and shared.reserved == reservation
    assert journal[1]["input_reserve"] == run_log[1]["input_reserve"] < 12000
    assert journal[1]["reservation_basis"]["kind"] == "metered_text_prefix"
    assert journal[1]["reservation_basis"]["prefix_input_tokens"] == 2000
    assert len(original) == 1 and len(grown) == 3
    await shared.settle(
        held,
        reservation,
        {"inputTokens": 0, "outputTokens": 0, "requestAttempts": 0, "retryUsageKnown": True},
        0,
    )
    assert not case.unknown and not shared.unknown


@pytest.mark.parametrize("change", ["edit", "insert", "tools", "multimodal", "unknown"])
async def test_changed_or_unknown_prefix_fails_before_factory(change):
    (
        model,
        case,
        shared,
        calls,
        _journal,
        _run_log,
        original,
        held,
        reservation,
    ) = await prefix_model()
    grown = original + [{"role": "user", "content": "continue"}]
    tools = []
    if change == "edit":
        grown[0] = {"role": "user", "content": "y" * 12000}
    elif change == "insert":
        grown.insert(0, {"role": "system", "content": "new policy"})
    elif change == "tools":
        tools = [{"type": "function", "function": {"name": "changed", "parameters": {}}}]
    elif change == "multimodal":
        grown[-1] = {"role": "user", "content": [{"type": "text", "text": "continue"}]}
    else:
        shared.unknown = True
    with pytest.raises(
        BudgetAdmissionRejected,
        match="RSI_USAGE_UNKNOWN" if change == "unknown" else "RSI_TOKEN_BUDGET",
    ):
        async for _ in model.stream(grown, tools):
            pass
    assert len(calls) == 1 and case.used == shared.used == 2100
    assert shared.reserved == reservation and case.reserved == 0
    await shared.settle(
        held,
        reservation,
        {"inputTokens": 0, "outputTokens": 0, "requestAttempts": 0, "retryUsageKnown": True},
        0,
    )


async def test_failed_stream_does_not_establish_a_prefix_reservation():
    from roami_agent.protocol.errors import DomainError

    settings = Settings()
    case = EpisodeBudget({"tokens": 30000, "seconds": 30, "requests": 6})
    shared = EpisodeBudget({"tokens": 30000, "seconds": 30, "requests": 6})
    calls = []

    class Failed:
        model = "failed-prefix"

        async def stream(self, messages, tools):
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 2000,
                    "outputTokens": 100,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )
            raise DomainError("MODEL_OUTPUT_LENGTH")

    def factory(config, role):
        calls.append(True)
        return MeteredModel(Failed(), shared, role, output_cap=1024)

    model = RequestBudgetModel(
        settings,
        settings.route("worker"),
        case,
        "worker",
        cap=1024,
        factory=factory,
        shared_budget=shared,
    )
    original = [{"role": "user", "content": "x" * 12000}]
    with pytest.raises(DomainError, match="MODEL_OUTPUT_LENGTH"):
        async for _ in model.stream(original, []):
            pass
    held, reservation = await shared.admit([], [], 12000)
    with pytest.raises(BudgetAdmissionRejected, match="RSI_TOKEN_BUDGET"):
        async for _ in model.stream(original + [{"role": "user", "content": "continue"}], []):
            pass
    assert len(calls) == 1 and case.used == shared.used == 2100
    assert not case.unknown and not shared.unknown
    await shared.settle(
        held,
        reservation,
        {"inputTokens": 0, "outputTokens": 0, "requestAttempts": 0, "retryUsageKnown": True},
        0,
    )


async def test_persistent_guest_meter_uses_the_same_known_prefix_bound():
    budget = EpisodeBudget({"tokens": 30000, "seconds": 30, "requests": 6})
    calls, journal = [], []

    class Provider:
        model = "guest-prefix"

        async def stream(self, messages, tools):
            calls.append(True)
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 2000 + 300 * (len(calls) - 1),
                    "outputTokens": 100,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )

    model = MeteredModel(Provider(), budget, "worker", output_cap=1024, journal=journal)
    original = [{"role": "user", "content": "x" * 12000}]
    async for _ in model.stream(original, []):
        pass
    held, reservation = await budget.admit([], [], 12000)
    async for _ in model.stream(original + [{"role": "user", "content": "continue"}], []):
        pass
    assert len(calls) == 2 and budget.used == 4500 and budget.reserved == reservation
    assert journal[1]["reservation_basis"]["kind"] == "metered_text_prefix"
    await budget.settle(
        held,
        reservation,
        {"inputTokens": 0, "outputTokens": 0, "requestAttempts": 0, "retryUsageKnown": True},
        0,
    )


@pytest.mark.parametrize("wrapper", ["role", "meter"])
async def test_admitted_input_is_immutable_while_waiting_on_budget(wrapper):
    settings = Settings()
    budget = EpisodeBudget({"tokens": 30000, "seconds": 30, "requests": 3})
    received = []

    class Provider:
        model = "frozen-input"

        async def stream(self, messages, tools):
            received.append((messages, tools))
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 100,
                    "outputTokens": 10,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )

    model = (
        RequestBudgetModel(
            settings,
            settings.route("worker"),
            budget,
            "worker",
            cap=1024,
            factory=lambda *_: Provider(),
        )
        if wrapper == "role"
        else MeteredModel(Provider(), budget, "worker", output_cap=1024)
    )
    messages = [{"role": "user", "content": "original"}]
    tools = [{"type": "function", "function": {"name": "original", "parameters": {}}}]

    async def consume():
        async for _ in model.stream(messages, tools):
            pass

    await budget.lock.acquire()
    pending = asyncio.create_task(consume())
    try:
        await asyncio.sleep(0)
        messages[0]["content"] = "changed after admission"
        tools[0]["function"]["name"] = "changed"
    finally:
        budget.lock.release()
    await pending
    assert received[0][0][0]["content"] == "original"
    assert received[0][1][0]["function"]["name"] == "original"
    assert messages[0]["content"] == "changed after admission"
