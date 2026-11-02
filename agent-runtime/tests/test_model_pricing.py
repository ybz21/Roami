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


async def test_legacy_accounting_preserves_cache_adjusted_prices_without_admission(store):
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
    await consume(model)
    assert len(requests) == 2
    await model.close()


@pytest.mark.parametrize("upstream_fee", [0, 0.05])
@pytest.mark.parametrize("priced", [False, True])
async def test_upstream_charge_including_zero_always_overrides_local_rates(
    store, upstream_fee, priced
):
    proxy, config = proxy_for(store, prices=priced)
    if priced:
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


async def test_adding_prices_does_not_reprice_old_zero_default_records(store):
    proxy, config = proxy_for(store, prices=False)
    old = await proxy.billing.admit("main", "fixture")
    await proxy.billing.settle(old, (1000, 100, 400))
    config["prices"] = {"fixture": PRICES}
    await proxy.billing.settle(old, (1000, 100, 400))
    new = await proxy.billing.admit("main", "fixture")
    await proxy.billing.settle(new, (1000, 100, 400))
    view = await proxy.billing.view()
    assert view["unknown"] == 0 and view["localEstimated"] == 2
    assert next(row for row in view["recent"] if row["id"] == old)["cost_amount"] == "0"


async def test_legacy_accounting_preserves_currency_without_admission(store):
    proxy, config = proxy_for(store, limit=1)
    config["prices"]["fixture"] = {**PRICES, "currency": "CNY"}
    call = await proxy.billing.admit("main", "fixture")
    await proxy.billing.settle(call, (1000, 100, 400))
    await proxy.billing.admit("main", "fixture")
    assert (await proxy.billing.view())["charges"] == [{"currency": "CNY", "amount": "0.00208"}]


@pytest.mark.parametrize("role", ["main", "worker", "memory"])
@pytest.mark.parametrize(
    "body,status",
    [
        (no_receipt(), 200),
        (b'data: {"choices":[]}\n\ndata: [DONE]\n\n', 200),
        (no_receipt().replace(b"data: [DONE]\n\n", b""), 200),
        (b"unavailable", 503),
    ],
)
async def test_unpriced_calls_allow_retry_without_usage_or_after_interruption(
    store, role, body, status
):
    proxy, _ = proxy_for(store, limit=1, prices=False)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"content-type": "text/event-stream"}, content=body)

    model = provider(proxy, handler, role)
    for _ in range(2):
        response = await model.client.post("http://127.0.0.1/v1/chat/completions")
        assert response.status_code == status and response.content == body
    view = await proxy.billing.view(days=1)
    assert len(calls) == view["requests"] == view["localEstimated"] == 2
    assert view["unknown"] == view["pending"] == 0
    assert view["failed"] == (2 if status == 503 else 0)
    assert view["charges"] == [{"currency": "USD", "amount": "0"}]
    assert view["statistics"]["total"]["charges"] == view["charges"]
    assert view["statistics"]["models"][0]["localCharges"] == view["charges"]
    await model.close()


async def test_zero_price_snapshot_survives_new_prices_currency_change_and_restart(store):
    proxy, config = proxy_for(store, prices=False)
    await proxy.ready()
    call = await proxy.billing.admit("main", "fixture")
    config.update(currency="CNY", dailyLimit=1, prices={"fixture": PRICES})
    restored, _ = proxy_for(store, limit=1)
    restored.billing.configuration = lambda: config
    await restored.ready()
    view = await restored.billing.view()
    row = next(row for row in view["recent"] if row["id"] == call)
    assert row["charges"] == [{"currency": "USD", "amount": "0"}]
    assert row["error_code"] == "MODEL_PROXY_INTERRUPTED"
    assert view["unknown"] == view["pending"] == 0
    await restored.billing.admit("worker", "fixture")


@pytest.mark.parametrize("state", ["unknown", "failed", "pending"])
async def test_restart_recovers_legacy_unpriced_unknown_calls_without_rewriting_receipts(
    store, state
):
    proxy, config = proxy_for(store, prices=False)
    await proxy.ready()
    legacy = await proxy.billing.admit("main", "fixture")
    await store.call(
        lambda db: db.execute(
            "UPDATE model_proxy_calls SET prices_json=NULL,state=?,input_tokens=1000,output_tokens=100,cache_read_tokens=400,error_code='OLD_ERROR' WHERE id=?",
            (state, legacy),
        ),
        write=True,
    )
    known = await proxy.billing.admit("worker", "fixture")
    await proxy.billing.settle(known, None, charge=UpstreamCharge(Decimal("0.25"), "USD"))
    config.update(dailyLimit=1, prices={"fixture": PRICES})
    restored, _ = proxy_for(store)
    restored.billing.configuration = lambda: config
    await restored.ready()
    view = await restored.billing.view()
    assert view["charges"] == [{"currency": "USD", "amount": "0.25"}]
    assert view["unknown"] == view["pending"] == 0
    assert view["inputTokens"] == 1000 and view["cacheReadTokens"] == 400
    old = next(row for row in view["recent"] if row["id"] == legacy)
    assert old["cost_source"] == "estimate" and old["cost_amount"] == "0"
    assert old["state"] == ("failed" if state == "failed" else "known")
    assert old["error_code"] == ("MODEL_PROXY_INTERRUPTED" if state == "pending" else "OLD_ERROR")
    await restored.billing.admit("main", "fixture")


async def test_priced_unknown_receipt_does_not_own_model_admission(store):
    proxy, _ = proxy_for(store, limit=1)
    await proxy.ready()
    call = await proxy.billing.admit("main", "fixture")
    await proxy.billing.settle(call, None)
    await proxy.billing.admit("worker", "unpriced")
    assert (await proxy.billing.view())["unknown"] == 1


async def test_legacy_zero_price_snapshot_without_currency_uses_legacy_cny(store):
    proxy, _ = proxy_for(store, prices=False)
    await proxy.ready()
    call = await proxy.billing.admit("main", "fixture")
    await store.call(
        lambda db: db.execute(
            "UPDATE model_proxy_calls SET state='unknown',prices_json=? WHERE id=?",
            (json.dumps({"input": 0, "output": 0}), call),
        ),
        write=True,
    )
    restored, _ = proxy_for(store, limit=1)
    await restored.ready()
    view = await restored.billing.view()
    assert view["charges"] == [{"currency": "CNY", "amount": "0"}]
    assert view["unknown"] == 0


async def test_legacy_upstream_charge_is_recorded_without_enforcing_limit(store):
    proxy, _ = proxy_for(store, limit=0.001, prices=False)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=EVENTS)

    model = provider(proxy, handler)
    await consume(model)
    await consume(model)
    assert len(calls) == 2
    await model.close()
