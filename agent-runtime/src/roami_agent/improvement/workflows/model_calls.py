"""Durable, metered model responses shared by RSI review and revision workflows."""

import asyncio
import json
from dataclasses import replace

from roami_agent.improvement.domain.contracts import require
from roami_agent.improvement.integrations.measurements import EpisodeBudget, MeteredModel
from roami_agent.protocol.model_routes import settings_with_route


async def model_json(workflow, action, settings, config, key, messages, *, provider_factory=None):
    if provider_factory is None:
        from roami_agent.improvement.workflows.codex_roles import codex_json

        return await codex_json(workflow, action, config, key, messages)

    from roami_agent.providers.factory import configured_provider

    route = settings.route("main")
    require(
        provider_factory is not None or bool(route.endpoint and route.name), "MODEL_NOT_CONFIGURED"
    )
    day = await asyncio.to_thread(workflow.day, action["owner"])
    operation = action["id"] + ":" + key
    cap = min(4096, route.parameters.get("max_tokens", 4096))
    reservation = len(json.dumps([messages, []], ensure_ascii=False).encode()) + 4096 + cap
    require(reservation <= config["model_tokens"], "RSI_TOKEN_BUDGET")
    saved = await asyncio.to_thread(
        workflow.reserve_operation, action["owner"], day, operation, reservation
    )
    if saved is not None:
        return saved["value"]
    route = replace(route, max_retries=0, parameters={**route.parameters, "max_tokens": cap})
    frozen = settings_with_route(settings, "main", route)
    provider = provider_factory(frozen) if provider_factory else configured_provider(frozen, "main")
    budget = EpisodeBudget(
        {"tokens": reservation, "seconds": config["model_seconds"], "requests": 1}
    )
    model = MeteredModel(provider, budget, "rsi_" + action["kind"], output_cap=cap)
    text = []
    try:
        async with asyncio.timeout(config["model_seconds"]):
            async for event in model.stream(messages, []):
                if event.kind == "text":
                    require(isinstance(event.value, str), "RSI_INVALID_MODEL_OUTPUT")
                    text.append(event.value)
                    require(sum(map(len, text)) <= 64000, "RSI_INVALID_MODEL_OUTPUT")
                require(event.kind != "tool", "RSI_UNEXPECTED_MODEL_TOOL")
        metrics = budget.metrics()
        require(metrics["tokens"] is not None, "RSI_USAGE_UNKNOWN")
        # Store paid output before interpreting it; malformed JSON must not trigger another call.
        result = {"text": "".join(text), "metrics": metrics}
        await asyncio.to_thread(
            workflow.settle_operation, action["owner"], operation, {"value": result}
        )
        return result
    finally:
        if hasattr(provider, "close"):
            await provider.close()
