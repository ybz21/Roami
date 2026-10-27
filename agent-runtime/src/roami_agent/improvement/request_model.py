"""Allocate each request's output from role settings and the remaining episode budget."""

import json
from contextlib import aclosing
from dataclasses import replace

from roami_agent.improvement.measurements import BudgetAdmissionRejected, MeteredModel
from roami_agent.protocol.model_routes import settings_with_route


class RequestBudgetModel:
    def __init__(
        self,
        settings,
        route,
        budget,
        role,
        *,
        cap=None,
        factory=None,
        journal=None,
        shared_budget=None,
    ):
        self.settings, self.route, self.budget, self.role = settings, route, budget, role
        self.cap, self.factory, self.journal = cap, factory, journal
        self.shared_budget = shared_budget
        self.model = route.name

    async def stream(self, messages, tools):
        from roami_agent.app import configured_provider

        overhead = len(json.dumps([messages, tools], ensure_ascii=False).encode()) + 4096
        available = 1_000_000
        for budget in (self.budget, self.shared_budget):
            if budget is None or not budget.enforce_tokens:
                continue
            async with budget.lock:
                budget.check()
                available = min(
                    available,
                    budget.limits["tokens"] - budget.used - budget.reserved - overhead,
                )
        if self.route.context_window:
            available = min(available, self.route.context_window - overhead)
        preferred = self.cap if self.cap is not None else self.route.parameters.get("max_tokens")
        if preferred is not None:
            available = min(available, preferred)
        else:
            available //= 2
        model_limit = self.route.capabilities.get("max_output_tokens")
        if type(model_limit) is int and model_limit > 0:
            available = min(available, model_limit)
        if available < 512:
            raise BudgetAdmissionRejected("RSI_TOKEN_BUDGET")
        route = replace(self.route, parameters={**self.route.parameters, "max_tokens": available})
        actual = "main" if self.role == "main" else "worker"
        settings = settings_with_route(self.settings, actual, route)
        provider = (
            self.factory(settings, self.role)
            if self.factory
            else configured_provider(settings, actual)
        )
        try:
            model = MeteredModel(
                provider, self.budget, self.role, output_cap=available, journal=self.journal
            )
            async with aclosing(model.stream(messages, tools)) as events:
                async for event in events:
                    yield event
        finally:
            if hasattr(provider, "close"):
                await provider.close()
