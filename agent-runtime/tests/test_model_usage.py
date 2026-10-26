import json
from datetime import UTC, datetime

import httpx
import pytest

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.providers.model_billing import ModelBilling
from roami_agent.providers.model_usage import usage_statistics
from roami_agent.server.http import create_app


async def seed_usage(store):
    rows = [
        ("old", "2026-07-01", "a", "known", 100, 10, 0, 4_000_000, True),
        ("a20", "2026-10-20", "a", "known", 100, 10, 20, 1_000_000, True),
        ("b20", "2026-10-20", "b", "known", 200, 20, 30, 2_000_000, True),
        ("a25", "2026-10-25", "a", "unknown", 50, 5, 10, None, False),
        ("a26", "2026-10-26", "a", "known", 300, 30, 100, 3_000_000, True),
        ("b26", "2026-10-26", "b", "failed", None, None, None, 0, True),
        ("c26", "2026-10-26", "c", "pending", None, None, None, None, True),
        ("d26", "2026-10-26", "d", "unknown", None, None, None, None, True),
        ("future", "2026-10-27", "future", "known", 9999, 9999, 0, 9_999_999, True),
    ]
    await store.call(
        lambda db: db.executemany(
            "INSERT INTO model_proxy_calls(id,day,timezone,role,model,started_ms,state,input_tokens,output_tokens,cache_read_tokens,cost_nano,prices_json,cost_source,cost_amount,cost_currency) VALUES(?,?,'Asia/Shanghai','main',?,0,?,?,?,?,?,?,?,?,?)",
            [
                (
                    i,
                    day,
                    model,
                    state,
                    tokens,
                    output,
                    cache,
                    cost,
                    json.dumps({"input": 9}) if priced else None,
                    "estimate"
                    if i == "old"
                    else "upstream"
                    if state == "known"
                    else "not_sent"
                    if state == "failed"
                    else "unknown",
                    str(cost / 1_000_000_000) if state == "known" and i != "old" else None,
                    "CNY" if i in {"old", "b20"} else "USD" if state == "known" else None,
                )
                for i, day, model, state, tokens, output, cache, cost, priced in rows
            ],
        ),
        write=True,
    )


async def test_daily_and_model_totals_reconcile_without_double_counting_cache(store):
    await seed_usage(store)
    result = await store.call(lambda db: usage_statistics(db, "2026-10-26", 7))
    total = result["total"]
    assert (result["startDay"], result["endDay"]) == ("2026-10-20", "2026-10-26")
    assert total == {
        "requests": 7,
        "charges": [{"currency": "CNY", "amount": "0.002"}, {"currency": "USD", "amount": "0.004"}],
        "estimatedCharges": [],
        "unknown": 2,
        "pending": 1,
        "failed": 1,
        "estimated": 0,
        "missingUsage": 1,
        "inputTokens": 650,
        "outputTokens": 65,
        "cacheReadTokens": 160,
        "totalTokens": 715,
    }
    assert len(result["daily"]) == 7 and result["daily"][1]["requests"] == 0
    for field in (
        "requests",
        "totalTokens",
        "inputTokens",
        "outputTokens",
        "cacheReadTokens",
        "unknown",
        "pending",
        "failed",
    ):
        assert sum(row[field] for row in result["daily"]) == total[field]
        assert sum(row[field] for row in result["models"]) == total[field]
    assert result["models"][0]["charges"] == [{"currency": "USD", "amount": "0.004"}]
    assert result["models"][1]["charges"] == [{"currency": "CNY", "amount": "0.002"}]
    assert [row["model"] for row in result["models"]] == ["a", "b", "c", "d"]


async def test_all_time_totals_include_history_while_daily_series_is_bounded(store):
    await seed_usage(store)
    result = await store.call(lambda db: usage_statistics(db, "2026-10-26", 0))
    assert result["startDay"] == "2026-07-01" and result["total"]["requests"] == 8
    assert result["total"]["estimatedCharges"] == [{"currency": "CNY", "amount": "0.004"}]
    assert result["total"]["estimated"] == 1 and result["total"]["totalTokens"] == 825
    assert result["total"]["charges"] == [
        {"currency": "CNY", "amount": "0.002"},
        {"currency": "USD", "amount": "0.004"},
    ]
    assert result["dailyStartDay"] == "2026-07-29" and len(result["daily"]) == 90
    assert sum(row["totalTokens"] for row in result["daily"]) == 715
    assert all(row["model"] != "future" for row in result["models"])


async def test_today_view_remains_today_when_statistics_select_another_period(store):
    await seed_usage(store)
    billing = ModelBilling(
        store,
        dict,
        lambda: "Asia/Shanghai",
        clock=lambda: int(datetime(2026, 10, 26, 4, tzinfo=UTC).timestamp() * 1000),
    )
    today = await billing.view(days=0)
    assert today["requests"] == 4 and today["charges"] == [{"currency": "USD", "amount": "0.003"}]
    assert today["statistics"]["total"]["requests"] == 8
    assert len(today["recent"]) == 4 and today["timezone"] == "Asia/Shanghai"
    day = await store.call(lambda db: usage_statistics(db, "2026-10-26", 1))
    assert len(day["daily"]) == 1 and day["total"]["requests"] == 4


@pytest.mark.parametrize("days", [0, 1, 7, 30, 90])
async def test_empty_period_returns_exact_zeroes_and_bounded_daily_rows(store, days):
    result = await store.call(lambda db: usage_statistics(db, "2026-10-26", days))
    assert result["total"]["requests"] == 0 and result["total"]["charges"] == []
    assert result["models"] == [] and result["modelsTruncated"] is False
    assert len(result["daily"]) == (days or 1)
    assert all(row["requests"] == row["totalTokens"] == 0 for row in result["daily"])


async def test_model_limit_does_not_truncate_totals(store):
    await store.call(
        lambda db: db.executemany(
            "INSERT INTO model_proxy_calls(id,day,timezone,role,model,started_ms,state,input_tokens,output_tokens,cache_read_tokens,cost_source,cost_amount,cost_currency) VALUES(?,'2026-10-26','UTC','main',?,0,'known',1,1,0,'upstream',?,'USD')",
            [(str(index), f"model-{index:03}", str(index / 1000)) for index in range(205)],
        ),
        write=True,
    )
    result = await store.call(lambda db: usage_statistics(db, "2026-10-26", 7))
    assert len(result["models"]) == 200 and result["modelsTruncated"] is True
    assert result["total"]["requests"] == 205 and result["total"]["totalTokens"] == 410
    assert result["models"][0]["model"] == "model-000"


@pytest.mark.parametrize("days", [-1, 91, True, "7"])
async def test_invalid_statistics_range_is_rejected(store, days):
    with pytest.raises(DomainError, match="INVALID_MODEL_USAGE_RANGE"):
        await store.call(lambda db: usage_statistics(db, "2026-10-26", days))


async def test_http_usage_range_validation_and_owner_isolation(store):
    class Model:
        async def stream(self, messages, tools):
            return
            yield

    runtime = Runtime(store, Model())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
        base_url="http://private",
        headers={"X-Roami-Owner": "local"},
    ) as client:
        response = await client.get("/v1/model-usage?days=30")
        assert response.status_code == 200
        assert len(response.json()["data"]["statistics"]["daily"]) == 30
        assert (await client.get("/v1/model-usage?days=0")).status_code == 200
        assert (await client.get("/v1/model-usage?days=91")).status_code == 422
        assert (await client.get("/v1/model-usage?days=bad")).status_code == 422
        assert (
            await client.get("/v1/model-usage?days=7", headers={"X-Roami-Owner": "other"})
        ).status_code == 403
    await runtime.close()


async def test_fee_sums_are_exact_and_zero_receipts_are_distinct_from_missing_fees(store):
    from decimal import Decimal

    from roami_agent.providers.upstream_costs import UpstreamCharge

    billing = ModelBilling(store, dict, lambda: "UTC")
    for fee in ["0.1", "0.2", "0"]:
        call = await billing.admit("main", "one")
        await billing.settle(call, None, charge=UpstreamCharge(Decimal(fee), "USD"))
    view = await billing.view()
    assert view["charges"] == [{"currency": "USD", "amount": "0.3"}]
    assert view["unknown"] == 0 and view["missingUsage"] == 3
    assert any(row["charges"] == [{"currency": "USD", "amount": "0"}] for row in view["recent"])


async def test_schema_13_migration_preserves_estimates_without_relabelling_as_receipts(
    tmp_path, monkeypatch
):
    from roami_agent.storage import migrations
    from roami_agent.storage.database import Database

    path = tmp_path / "runtime.db"
    with monkeypatch.context() as old:
        old.setattr(migrations, "SCHEMA_VERSION", 13)
        database = Database(path, tmp_path, managed=False)
        await database.open()
        await database.call(
            lambda db: db.execute(
                "INSERT INTO model_proxy_calls(id,day,timezone,role,model,started_ms,state,cost_nano,prices_json) VALUES('old','2026-10-26','UTC','main','a',0,'known',123456789,'{}')"
            ),
            write=True,
        )
        await database.close()
    database = Database(path, tmp_path, managed=False)
    await database.open()
    try:
        result = await database.call(lambda db: usage_statistics(db, "2026-10-26", 1))
        assert result["total"]["charges"] == []
        assert result["total"]["estimatedCharges"] == [{"currency": "CNY", "amount": "0.123456789"}]
        assert result["total"]["unknown"] == result["total"]["estimated"] == 1
        billing = ModelBilling(
            database,
            lambda: {"dailyLimit": 1, "currency": "CNY"},
            lambda: "UTC",
            clock=lambda: int(datetime(2026, 10, 26, tzinfo=UTC).timestamp() * 1000),
        )
        with pytest.raises(DomainError, match="MODEL_PROXY_USAGE_UNKNOWN"):
            await billing.admit("main", "a")
    finally:
        await database.close()


async def test_large_totals_retain_all_fractional_digits(store):
    from decimal import Decimal

    from roami_agent.providers.upstream_costs import UpstreamCharge

    billing = ModelBilling(store, dict, lambda: "UTC")
    for _ in range(101):
        call = await billing.admit("main", "one")
        await billing.settle(
            call, None, charge=UpstreamCharge(Decimal("999999999.123456789012345678"), "USD")
        )
    assert (await billing.view())["charges"] == [
        {"currency": "USD", "amount": "100999999911.469135690246913478"}
    ]
