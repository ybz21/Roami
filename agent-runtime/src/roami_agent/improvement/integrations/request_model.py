"""Preserve configured model requests and observe usage; Go decides admission."""

import json
from contextlib import aclosing

from roami_agent.improvement.integrations.input_reservation import InputReservation
from roami_agent.improvement.integrations.measurements import MeteredModel
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
        input_reserve, snapshot, basis = self.input_reservation.estimate(messages, tools)
        available = self.route.parameters.get("max_tokens") or 0
        actual = "main" if self.role == "main" else "worker"
        settings = settings_with_route(self.settings, actual, self.route)
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
                input_reserve=input_reserve,
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
