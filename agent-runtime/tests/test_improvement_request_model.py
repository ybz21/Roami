import asyncio
from dataclasses import replace

import pytest

from roami_agent.improvement.integrations.measurements import (
    EpisodeBudget,
    MeteredModel,
)
from roami_agent.improvement.integrations.request_model import RequestBudgetModel
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings


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
        calls.append(config.route("worker").parameters.get("max_tokens", 0))
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
async def test_changed_or_unknown_prefix_is_observed_without_admission_cap(change):
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
    async for _ in model.stream(grown, tools):
        pass
    assert len(calls) == 2 and case.used == shared.used == 4500
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
    with pytest.raises(DomainError, match="MODEL_OUTPUT_LENGTH"):
        async for _ in model.stream(original + [{"role": "user", "content": "continue"}], []):
            pass
    assert len(calls) == 2 and case.used == shared.used == 4200
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


async def test_shared_daily_policy_keeps_model_settings_without_rsi_pressure_or_caps():
    settings = Settings()
    route = replace(settings.route("worker"), parameters={"max_tokens": 32768})
    observed = []

    class Provider:
        model = "fixture"

        async def stream(self, messages, tools):
            observed.append(messages)
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 20000,
                    "outputTokens": 1000,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )

        async def close(self):
            pass

    def factory(frozen, role):
        assert frozen.route("worker").parameters["max_tokens"] == 32768
        return Provider()

    budget = EpisodeBudget({"tokens": 1, "requests": 1, "seconds": 10}, shared_daily_limit=True)
    model = RequestBudgetModel(settings, route, budget, "worker", cap=512, factory=factory)
    for _ in range(2):
        async for _ in model.stream([{"role": "user", "content": "task"}], []):
            pass
    assert len(observed) == 2 and budget.used == 42000
    assert all(messages == [{"role": "user", "content": "task"}] for messages in observed)
    budget.unknown = True
    async for _ in model.stream([], []):
        pass
    assert len(observed) == 3 and budget.used == 63000
    assert budget.metrics()["tokens"] is None
