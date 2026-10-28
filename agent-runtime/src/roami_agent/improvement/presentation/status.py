"""Owner-scoped experiment API projections over repositories and coordinators."""

import asyncio

from roami_agent.improvement.presentation.run_overview import run_overview


async def overview(service, owner):
    def read():
        return {
            "preferences": service.control.preferences_view(owner),
            "catalog": service.control.catalog(owner),
            "releases": service.releases.list(owner),
            "requests": service.control.requests(owner),
            "cycles": service.ledger.list(owner),
            "research": service.research.snapshot(owner),
            "pipeline": run_overview(service.runs, owner),
        }

    result = await asyncio.to_thread(read)
    proxy = getattr(service, "model_proxy", None)
    if proxy is not None:
        from roami_agent.providers.model_billing import proxy_configuration

        usage = await proxy.billing.daily_summary()
        config = proxy_configuration(proxy.billing.configuration())
        result["billing"] = {
            "dailyLimit": config["dailyLimit"],
            "currency": config["currency"],
            **{
                key: usage[key]
                for key in ("day", "timezone", "charges", "localCharges", "unknown", "pending")
            },
        }
    return result


async def list_cycles(service, owner, limit=20):
    return {
        "version": 1,
        "cycles": await asyncio.to_thread(service.ledger.list, owner, limit),
        "live_policy_automatically_modified": False,
    }


async def get_cycle(service, owner, cycle_id):
    if cycle_id.startswith("period-"):
        report = await asyncio.to_thread(service.research.report, owner, cycle_id)
        return {
            "id": cycle_id,
            "state": "completed",
            "day": report["day"],
            "report": None,
            "review_document": report["document"],
        }
    cycle = await asyncio.to_thread(service.ledger.get, owner, cycle_id)

    # Hidden tasks' prompts, outputs, oracle and trial traces are absent from this endpoint.
    return {
        **{k: cycle[k] for k in ("id", "state", "day", "report")},
        "review_document": await asyncio.to_thread(
            service.research.review_document, owner, cycle_id
        ),
    }
