import json
from decimal import Decimal

import httpx
import pytest
from test_model_proxy import EVENTS, PRICES, consume, provider, proxy_for

from roami_agent.protocol.errors import DomainError
from roami_agent.providers.model_billing import proxy_configuration
from roami_agent.providers.upstream_costs import UpstreamCharge


def no_receipt():
    return EVENTS.replace(b'"cost": 0.00208, ', b"")


@pytest.mark.parametrize(
    "rates",
    [
        {"input": 1},
        {"input": True, "output": 1},
        {"input": -1, "output": 1},
        {"input": 1, "output": float("nan")},
        {"input": 1, "output": 1, "cacheRead": -1},
        {"input": 0.0000001, "output": 1},
        {"input": 1, "output": "2"},
        {"input": 1, "output": 2, "currency": "usd"},
        {"input": 1, "output": 2, "other": 1},
    ],
)
def test_invalid_prices_are_rejected(rates):
    with pytest.raises(DomainError, match="INVALID_MODEL_PROXY_CONFIG"):
        proxy_configuration({"prices": {"fixture": rates}})


@pytest.mark.parametrize(
    "prices",
    [{"": PRICES}, {" fixture ": PRICES}, {"m" * 201: PRICES}, {str(i): PRICES for i in range(33)}],
)
def test_invalid_model_price_catalog_is_rejected(prices):
    with pytest.raises(DomainError, match="INVALID_MODEL_PROXY_CONFIG"):
        proxy_configuration({"prices": prices})


async def test_fallback_uses_exact_cache_adjusted_price_and_enforces_daily_limit(store):
    proxy, _ = proxy_for(store, limit=0.002)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=no_receipt()
        )

    model = provider(proxy, handler)
    await consume(model)
    view = await proxy.billing.view(days=1)
    expected = [{"currency": "USD", "amount": "0.00208"}]
    assert view["charges"] == view["localCharges"] == expected
    assert view["localEstimated"] == 1 and view["unknown"] == view["estimated"] == 0
    assert view["recent"][0]["cost_source"] == "estimate"
    assert view["recent"][0]["localCharges"] == expected
    for point in [*view["statistics"]["daily"], *view["statistics"]["hourly"]]:
        if point["requests"]:
            assert point["charges"] == point["localCharges"] == expected
            assert point["models"][0]["localCharges"] == expected
            assert point["unknown"] == 0 and point["localEstimated"] == 1
    with pytest.raises(DomainError, match="MODEL_PROXY_DAILY_LIMIT"):
        await consume(model)
    assert len(requests) == 1
    await model.close()


@pytest.mark.parametrize("upstream_fee", [0, 0.05])
async def test_upstream_charge_including_zero_always_overrides_local_rates(store, upstream_fee):
    proxy, config = proxy_for(store)
    config["prices"]["fixture"] = {"currency": "CNY", "input": 999, "output": 999}
    model = provider(
        proxy,
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=EVENTS.replace(b'"cost": 0.00208', ('"cost": ' + str(upstream_fee)).encode()),
        ),
    )
    await consume(model)
    view = await proxy.billing.view()
    assert view["charges"] == [{"currency": "USD", "amount": str(upstream_fee)}]
    assert view["localCharges"] == [] and view["localEstimated"] == 0
    assert view["recent"][0]["cost_source"] == "upstream"
    await model.close()


async def test_price_snapshot_survives_rate_changes_and_settles_only_once(store):
    proxy, config = proxy_for(store)
    await proxy.ready()
    call = await proxy.billing.admit("main", "fixture")
    config["prices"]["fixture"] = {"currency": "CNY", "input": 500, "output": 500}
    await proxy.billing.settle(call, (1000, 100, 400))
    await proxy.billing.settle(call, (1, 1, 0), charge=UpstreamCharge(Decimal(99), "CNY"))
    view = await proxy.billing.view()
    assert view["charges"] == [{"currency": "USD", "amount": "0.00208"}]
    assert view["localEstimated"] == 1 and view["inputTokens"] == 1000
    snapshot = await store.call(
        lambda db: db.execute(
            "SELECT prices_json FROM model_proxy_calls WHERE id=?", (call,)
        ).fetchone()[0]
    )
    assert json.loads(snapshot)["input"] == 2


@pytest.mark.parametrize(
    "rate,expected", [({"input": 2, "output": 8}, "0.0028"), ({"input": 0, "output": 0}, "0")]
)
async def test_blank_cache_price_uses_input_price_and_zero_prices_are_known(store, rate, expected):
    proxy, config = proxy_for(store, limit=1)
    config["prices"]["fixture"] = rate
    model = provider(
        proxy,
        lambda request: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=no_receipt()
        ),
    )
    await consume(model)
    await consume(model)
    view = await proxy.billing.view()
    assert view["unknown"] == 0 and view["localEstimated"] == 2
    assert all(row["cost_amount"] == expected for row in view["recent"])
    await model.close()


async def test_mixed_receipts_and_estimates_sum_without_hiding_local_source(store):
    proxy, _ = proxy_for(store)
    first = await proxy.billing.admit("main", "fixture")
    await proxy.billing.settle(
        first, (1000, 100, 400), charge=UpstreamCharge(Decimal("0.1"), "USD")
    )
    second = await proxy.billing.admit("worker", "fixture")
    await proxy.billing.settle(second, (1000, 100, 400))
    view = await proxy.billing.view(days=1)
    assert view["charges"] == [{"currency": "USD", "amount": "0.10208"}]
    assert view["localCharges"] == [{"currency": "USD", "amount": "0.00208"}]
    assert view["localEstimated"] == 1 and view["unknown"] == 0
    assert view["statistics"]["total"]["localCharges"] == view["localCharges"]
    assert view["statistics"]["models"][0]["charges"] == view["charges"]


async def test_adding_prices_does_not_reprice_old_unknown_records(store):
    proxy, config = proxy_for(store, prices=False)
    old = await proxy.billing.admit("main", "fixture")
    await proxy.billing.settle(old, (1000, 100, 400))
    config["prices"] = {"fixture": PRICES}
    await proxy.billing.settle(old, (1000, 100, 400))
    new = await proxy.billing.admit("main", "fixture")
    await proxy.billing.settle(new, (1000, 100, 400))
    view = await proxy.billing.view()
    assert view["unknown"] == 1 and view["localEstimated"] == 1
    assert next(row for row in view["recent"] if row["id"] == old)["cost_amount"] is None


async def test_fallback_currency_is_checked_against_limit_and_never_converted(store):
    proxy, config = proxy_for(store, limit=1)
    config["prices"]["fixture"] = {**PRICES, "currency": "CNY"}
    call = await proxy.billing.admit("main", "fixture")
    await proxy.billing.settle(call, (1000, 100, 400))
    with pytest.raises(DomainError, match="MODEL_PROXY_CURRENCY_MISMATCH"):
        await proxy.billing.admit("main", "fixture")
