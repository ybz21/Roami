import asyncio
import json
from dataclasses import replace
from decimal import Decimal

import httpx
import pytest
from test_improvement_codex_roles import codex_events
from test_improvement_workflow import setup
from test_model_proxy import EVENTS, consume, proxy_for

from roami_agent.app import configured_provider
from roami_agent.improvement.codex_roles import codex_json
from roami_agent.improvement.measurements import EpisodeBudget
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.model_routes import settings_with_route
from roami_agent.providers.model_proxy import model_accounting
from roami_agent.providers.upstream_costs import UpstreamCharge
from roami_agent.server.configuration import Settings


async def test_rsi_provider_ignores_legacy_token_admission_but_shares_the_daily_cost_limit(store):
    proxy, _ = proxy_for(store, limit=0.002)
    settings = Settings()
    route = replace(settings.route("worker"), endpoint="https://provider.test/v1", name="fixture")
    settings = settings_with_route(settings, "worker", route)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=EVENTS)

    with model_accounting(proxy):
        budget = EpisodeBudget({"tokens": 1, "seconds": 20, "requests": 3})
        entry, estimate = await budget.admit([{"role": "user", "content": "fixture"}], [], 8192)
        assert not budget.enforce_tokens
        await budget.settle(
            entry,
            estimate,
            {
                "inputTokens": 1000,
                "outputTokens": 100,
                "requestAttempts": 1,
                "retryUsageKnown": True,
            },
            0.1,
        )
        model = configured_provider(
            settings, "worker", client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        assert proxy.attach(model, "worker") is model
        await consume(model)
        with pytest.raises(DomainError, match="MODEL_PROXY_DAILY_LIMIT"):
            await consume(model)
        await model.close()
    assert len(requests) == 1
    summary = await proxy.billing.daily_summary()
    assert summary["charges"] == [{"currency": "USD", "amount": "0.00208"}]
    assert summary["requests"] == 1


async def test_codex_turns_are_priced_once_and_limit_rejection_does_not_poison_the_operation(
    store, tmp_path, monkeypatch
):
    workflow, config, *_ = await setup(tmp_path)
    home = tmp_path / "codex-settings"
    home.mkdir()
    (home / "config.toml").write_text('model = "fixture"\n')
    monkeypatch.setenv("CODEX_HOME", str(home))
    proxy, pricing = proxy_for(store, limit=0.0003)
    calls = []

    async def runner(*args, **kwargs):
        calls.append(1)
        return {"stdout": codex_events(), "stderr": "", "exitCode": 0}

    action = {"id": "priced-codex", "owner": "owner", "kind": "review"}
    with model_accounting(proxy):
        first = await codex_json(
            workflow, action, {**config, "model_tokens": 1}, "one", [], runner=runner
        )
        cached = await codex_json(
            workflow, action, {**config, "model_tokens": 1}, "one", [], runner=runner
        )
        assert first == cached and len(calls) == 1
        with pytest.raises(DomainError, match="MODEL_PROXY_DAILY_LIMIT"):
            await codex_json(workflow, action, config, "two", [], runner=runner)
        assert workflow.operation_result("owner", "priced-codex:two") is None
        pricing["dailyLimit"] = 1
        await codex_json(workflow, action, config, "two", [], runner=runner)
    assert len(calls) == 2
    summary = await proxy.billing.view(days=1)
    assert summary["localEstimated"] == 2 and summary["unknown"] == 0
    assert summary["localCharges"] == [{"currency": "USD", "amount": "0.000684"}]
    assert all(row["model"] == "fixture" for row in summary["recent"])


async def test_native_spending_also_stops_codex_before_process_launch(store, tmp_path, monkeypatch):
    workflow, config, *_ = await setup(tmp_path)
    home = tmp_path / "codex-settings"
    home.mkdir()
    (home / "config.toml").write_text('model = "fixture"\n')
    monkeypatch.setenv("CODEX_HOME", str(home))
    proxy, _ = proxy_for(store, limit=1)
    await proxy.ready()
    call = await proxy.billing.admit("main", "fixture")
    await proxy.billing.settle(call, (100, 20, 0), charge=UpstreamCharge(Decimal(1), "USD"))
    calls = []

    async def runner(*args, **kwargs):
        calls.append(1)

    with model_accounting(proxy), pytest.raises(DomainError, match="MODEL_PROXY_DAILY_LIMIT"):
        await codex_json(
            workflow,
            {"id": "after-native", "owner": "owner", "kind": "review"},
            config,
            "one",
            [],
            runner=runner,
        )
    assert calls == []


async def test_missing_codex_usage_stays_unknown_and_cannot_replay(store, tmp_path, monkeypatch):
    workflow, config, *_ = await setup(tmp_path)
    home = tmp_path / "codex-settings"
    home.mkdir()
    (home / "config.toml").write_text('model = "fixture"\n')
    monkeypatch.setenv("CODEX_HOME", str(home))
    proxy, _ = proxy_for(store, limit=1)
    calls = []

    async def interrupted(*args, **kwargs):
        calls.append(1)
        raise TimeoutError

    action = {"id": "unknown-codex", "owner": "owner", "kind": "review"}
    with model_accounting(proxy):
        with pytest.raises(TimeoutError):
            await codex_json(workflow, action, config, "one", [], runner=interrupted)
        with pytest.raises(DomainError, match="UNKNOWN_OPERATION"):
            await codex_json(workflow, action, config, "one", [], runner=interrupted)
        with pytest.raises(DomainError, match="MODEL_PROXY_USAGE_UNKNOWN"):
            await proxy.billing.check()
    assert calls == [1]
    assert (await proxy.billing.daily_summary())["unknown"] == 1


async def test_invalid_codex_content_still_accounts_completed_usage(store, tmp_path, monkeypatch):
    workflow, config, *_ = await setup(tmp_path)
    home = tmp_path / "codex-settings"
    home.mkdir()
    (home / "config.toml").write_text('model = "fixture"\n')
    monkeypatch.setenv("CODEX_HOME", str(home))
    proxy, _ = proxy_for(store)

    async def runner(*args, **kwargs):
        events = [json.loads(line) for line in codex_events().splitlines()]
        events = [event for event in events if event["type"] != "item.completed"]
        return {
            "stdout": "\n".join(json.dumps(event) for event in events),
            "stderr": "",
            "exitCode": 0,
        }

    with model_accounting(proxy), pytest.raises(DomainError, match="INVALID_MODEL_OUTPUT"):
        await codex_json(
            workflow,
            {"id": "invalid-content", "owner": "owner", "kind": "review"},
            config,
            "one",
            [],
            runner=runner,
        )
    summary = await proxy.billing.daily_summary()
    assert summary["localCharges"] == [{"currency": "USD", "amount": "0.000342"}]
    assert summary["unknown"] == 0


async def test_cancelled_external_admission_is_not_sent_and_releases_the_shared_lock(
    store, monkeypatch
):
    proxy, _ = proxy_for(store, limit=1)
    started, released = asyncio.Event(), asyncio.Event()
    admit = proxy.billing.admit

    async def delayed(*args):
        started.set()
        await released.wait()
        return await admit(*args)

    monkeypatch.setattr(proxy.billing, "admit", delayed)

    async def call():
        async with proxy.external_turn("worker", "fixture"):
            pytest.fail("Cancelled admission must not launch the CLI")

    task = asyncio.create_task(call())
    await started.wait()
    task.cancel()
    released.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not proxy.admission.locked()
    await proxy.billing.check()
    summary = await proxy.billing.view(days=1)
    assert summary["pending"] == summary["unknown"] == 0
    assert summary["recent"][0]["cost_source"] == "not_sent"


async def test_codex_requires_model_identity_before_reserving_any_operation(
    store, tmp_path, monkeypatch
):
    workflow, config, *_ = await setup(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-codex-config"))
    proxy, _ = proxy_for(store, limit=1)

    async def runner(*args, **kwargs):
        pytest.fail("Unknown model identity must not launch a paid call")

    with model_accounting(proxy), pytest.raises(DomainError, match="RSI_CODEX_MODEL_REQUIRED"):
        await codex_json(
            workflow,
            {"id": "missing-model", "owner": "owner", "kind": "review"},
            config,
            "one",
            [],
            runner=runner,
        )
    assert workflow.operation_result("owner", "missing-model:one") is None
    assert (await proxy.billing.daily_summary())["requests"] == 0


async def test_waiting_research_uses_the_shared_billing_day_without_a_new_token_budget_row(
    store, tmp_path
):
    workflow, _config, *_ = await setup(tmp_path)
    proxy, _ = proxy_for(store, limit=1)
    workflow.model_proxy = proxy
    timestamp = [1793030400000]
    proxy.billing.clock = lambda: timestamp[0]
    with workflow.ledger.connection() as db:
        workflow._enqueue(db, "owner", "review", "budget-wait", {"cycle_id": "fixture-cycle"})
    action = workflow.claim()
    assert action is not None
    workflow.block(action, "MODEL_PROXY_DAILY_LIMIT")
    with workflow.ledger.connection() as db:
        assert (
            db.execute("SELECT state FROM rsi_actions WHERE id=?", (action["id"],)).fetchone()[0]
            == "waiting_budget"
        )
    timestamp[0] += 86400000
    workflow.discover()
    with workflow.ledger.connection() as db:
        assert (
            db.execute("SELECT state FROM rsi_actions WHERE id=?", (action["id"],)).fetchone()[0]
            == "queued"
        )


async def test_overview_reuses_a_stable_daily_summary_until_usage_changes(store):
    proxy, _ = proxy_for(store)
    await proxy.ready()
    first = await proxy.billing.daily_summary()
    assert await proxy.billing.daily_summary() is first
    call = await proxy.billing.admit("worker", "fixture")
    pending = await proxy.billing.daily_summary()
    assert pending["pending"] == 1 and pending is not first
    await proxy.billing.settle(call, (100, 20, 10))
    settled = await proxy.billing.daily_summary()
    assert settled["pending"] == 0 and settled["localEstimated"] == 1
    assert await proxy.billing.daily_summary() is settled
