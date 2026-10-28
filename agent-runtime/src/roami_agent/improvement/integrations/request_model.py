"""Allocate each request's output from role settings and the remaining episode budget."""

import json
from contextlib import aclosing
from dataclasses import replace

from roami_agent.improvement.integrations.input_reservation import InputReservation, input_bytes
from roami_agent.improvement.integrations.measurements import BudgetAdmissionRejected, MeteredModel
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
        observation_role=None,
    ):
        self.settings, self.route, self.budget, self.role = settings, route, budget, role
        self.cap, self.factory, self.journal = cap, factory, journal
        self.shared_budget = shared_budget
        self.observation_role = observation_role or role
        self.model = route.name
        self.input_reservation = InputReservation()

    async def stream(self, messages, tools):
        from roami_agent.providers.factory import configured_provider

        messages, tools = json.loads(json.dumps([messages, tools], ensure_ascii=False))
        original_bytes = input_bytes(messages, tools)
        input_reserve, snapshot, basis = self.input_reservation.estimate(messages, tools)
        if self.budget.shared_daily_limit:
            overhead = input_reserve
            available = self.route.parameters.get("max_tokens") or 0
            route = self.route
        else:
            remaining = 100_000_000
            for budget in (self.budget, self.shared_budget):
                if budget is None:
                    continue
                async with budget.lock:
                    budget.check()
                    remaining = min(
                        remaining, budget.limits["tokens"] - budget.used - budget.reserved
                    )
            if self.role in {"main", "worker"}:
                pressure = remaining < 2 * (input_reserve + 512)
                notice = (
                    f"Execution allowance: at most {remaining} metered tokens remain across roles "
                    f"and shared limits. This request's input needs a conservative reserve of "
                    f"{input_reserve} units before this notice ({basis['kind']} plus margin, not billed tokens). "
                    "Each later request also needs its input and output reserve. Keep tool output bounded; "
                    "return requested files and verified findings when ready, and state unverified requirements "
                    "or failed/unknown outcomes plainly. This allowance is not evidence of task completion."
                )
                if pressure:
                    notice += (
                        " Budget pressure: another round-trip at this context size may not fit. "
                        "Prioritize essential work and a concise handoff over new verification infrastructure."
                    )
                messages = [*messages, {"role": "system", "content": notice}]
            overhead = input_reserve + input_bytes(messages, tools) - original_bytes
            available = min(1_000_000, remaining - overhead)
            if self.route.context_window:
                available = min(available, self.route.context_window - overhead)
            preferred = (
                self.cap if self.cap is not None else self.route.parameters.get("max_tokens")
            )
            if preferred is not None:
                available = min(available, preferred)
            else:
                available //= 2
            model_limit = self.route.capabilities.get("max_output_tokens")
            if type(model_limit) is int and model_limit > 0:
                available = min(available, model_limit)
            if available < 512:
                raise BudgetAdmissionRejected("RSI_TOKEN_BUDGET")
            route = replace(
                self.route, parameters={**self.route.parameters, "max_tokens": available}
            )
        actual = "main" if self.role == "main" else "worker"
        settings = settings_with_route(self.settings, actual, route)
        provider = (
            self.factory(settings, self.role)
            if self.factory
            else configured_provider(settings, actual)
        )
        try:
            model = MeteredModel(
                provider,
                self.budget,
                self.observation_role,
                output_cap=available,
                journal=self.journal,
                input_reserve=overhead,
                reservation_basis=basis,
            )
            usage = None
            async with aclosing(model.stream(messages, tools)) as events:
                async for event in events:
                    if event.kind == "usage":
                        usage = dict(event.value)
                    yield event
            self.input_reservation.observe(snapshot, usage)
        finally:
            if hasattr(provider, "close"):
                await provider.close()
