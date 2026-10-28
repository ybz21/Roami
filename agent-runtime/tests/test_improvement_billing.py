import asyncio
import json
from dataclasses import replace
from decimal import Decimal
from itertools import pairwise

import httpx
import pytest
from test_improvement_codex_roles import codex_events
from test_improvement_workflow import setup
from test_model_proxy import EVENTS, consume, proxy_for

from roami_agent.app import configured_provider
from roami_agent.improvement.integrations.codex_proxy import CodexProxy
from roami_agent.improvement.integrations.measurements import EpisodeBudget
from roami_agent.improvement.workflows.codex_roles import codex_json
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.model_routes import settings_with_route
from roami_agent.providers.model_proxy import model_accounting
from roami_agent.providers.upstream_costs import UpstreamCharge
from roami_agent.server.configuration import Settings


@pytest.fixture
def codex_responses(monkeypatch):
    original = CodexProxy.__init__

    def handler(request):
        assert request.url.path.endswith("/responses")
        complete = json.loads(request.content).get("complete", True)
        event = {
            "type": "response.completed" if complete else "response.in_progress",
            "response": {
                "status": "completed" if complete else "in_progress",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "input_tokens_details": {"cached_tokens": 10},
                },
            },
        }
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=("data: " + json.dumps(event) + "\n\n").encode(),
        )

    def initialize(self, *args, **kwargs):
        kwargs["upstream_client"] = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        original(self, *args, **kwargs)

    monkeypatch.setattr(CodexProxy, "__init__", initialize)

    async def request(argv, env, *, complete=True, expected=200):
        settings = dict(value.split("=", 1) for flag, value in pairwise(argv) if flag == "-c")
        address = next(
            json.loads(value) for key, value in settings.items() if key.endswith(".base_url")
        )
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.post(
                address + "/responses",
                headers={"X-Roami-Rsi-Key": env["ROAMI_RSI_CODEX_PROXY_KEY"]},
                json={"complete": complete},
            )
        if expected is not None:
            assert response.status_code == expected
        return response

    return request


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
    store, tmp_path, monkeypatch, codex_responses
):
    workflow, config, *_ = await setup(tmp_path)
    home = tmp_path / "codex-settings"
    home.mkdir()
    (home / "config.toml").write_text('model = "fixture"\n')
    monkeypatch.setenv("CODEX_HOME", str(home))
    proxy, pricing = proxy_for(store, limit=0.0003)
    calls = []

    async def runner(argv, **kwargs):
        calls.append(1)
        response = await codex_responses(argv, kwargs["env"], expected=None)
        return {
            "stdout": codex_events(),
            "stderr": "",
            "exitCode": 0 if response.status_code == 200 else 1,
        }

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
        rejected = workflow.operation_result("owner", "priced-codex:two")["value"]
        assert rejected["admission_rejected"] and rejected["metrics"]["tokens"] == 0
        pricing["dailyLimit"] = 1
        await codex_json(workflow, action, config, "two", [], runner=runner)
    assert len(calls) == 3
    summary = await proxy.billing.view(days=1)
    assert summary["localEstimated"] == 2 and summary["unknown"] == 0
    assert summary["localCharges"] == [{"currency": "USD", "amount": "0.000684"}]
    assert all(row["model"] == "fixture" for row in summary["recent"])


async def test_native_spending_is_rejected_by_the_legacy_transport(
    store, tmp_path, monkeypatch, codex_responses
):
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

    async def runner(argv, **kwargs):
        calls.append(1)
        await codex_responses(argv, kwargs["env"], expected=429)
        return {"stdout": "", "stderr": "Daily limit", "exitCode": 1}

    with model_accounting(proxy), pytest.raises(DomainError, match="MODEL_PROXY_DAILY_LIMIT"):
        await codex_json(
            workflow,
            {"id": "after-native", "owner": "owner", "kind": "review"},
            config,
            "one",
            [],
            runner=runner,
        )
    assert calls == [1]


async def test_missing_codex_usage_stays_unknown_and_cannot_replay(
    store, tmp_path, monkeypatch, codex_responses
):
    workflow, config, *_ = await setup(tmp_path)
    home = tmp_path / "codex-settings"
    home.mkdir()
    (home / "config.toml").write_text('model = "fixture"\n')
    monkeypatch.setenv("CODEX_HOME", str(home))
    proxy, _ = proxy_for(store, limit=1)
    calls = []

    async def interrupted(argv, **kwargs):
        calls.append(1)
        await codex_responses(argv, kwargs["env"], complete=False)
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


async def test_invalid_codex_content_still_accounts_completed_usage(
    store, tmp_path, monkeypatch, codex_responses
):
    workflow, config, *_ = await setup(tmp_path)
    home = tmp_path / "codex-settings"
    home.mkdir()
    (home / "config.toml").write_text('model = "fixture"\n')
    monkeypatch.setenv("CODEX_HOME", str(home))
    proxy, _ = proxy_for(store)

    async def runner(argv, **kwargs):
        await codex_responses(argv, kwargs["env"])
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


async def test_proxy_admission_rejection_is_known_zero_without_poisoning_rsi_usage(store):
    from test_model_proxy import provider

    from roami_agent.improvement.integrations.measurements import MeteredModel

    proxy, _ = proxy_for(store, limit=0.002)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=EVENTS)

    upstream = provider(proxy, handler)
    budget = EpisodeBudget({"tokens": 1, "requests": 1, "seconds": 10}, shared_daily_limit=True)
    journal = []
    measured = MeteredModel(upstream, budget, "main", output_cap=0, journal=journal)
    try:
        await consume(measured)
        with pytest.raises(DomainError, match="MODEL_PROXY_DAILY_LIMIT"):
            await consume(measured)
        assert len(calls) == 1
        metrics = budget.metrics()
        assert metrics["tokens"] == 1100 and metrics["request_attempts"] == 1
        assert not budget.unknown
        assert journal[-1]["admission_rejected"] is True
        assert journal[-1]["measurement"]["inputTokens"] == 0
        summary = await proxy.billing.daily_summary()
        assert summary["requests"] == 1 and summary["unknown"] == 0
    finally:
        await upstream.close()


@pytest.mark.parametrize("code", ["MODEL_PROXY_DAILY_LIMIT", "MODEL_PROXY_USAGE_UNKNOWN"])
async def test_error_text_alone_cannot_claim_an_unsent_free_request(code):
    from roami_agent.improvement.integrations.measurements import MeteredModel

    class Uncertain:
        model = "uncertain-fixture"

        async def stream(self, messages, tools):
            raise DomainError(code)
            yield

    budget = EpisodeBudget({"tokens": 1, "requests": 1, "seconds": 10}, shared_daily_limit=True)
    with pytest.raises(DomainError, match=code):
        await consume(MeteredModel(Uncertain(), budget, "main", output_cap=0))
    assert budget.unknown and budget.metrics()["tokens"] is None


async def test_retry_admission_rejection_preserves_the_first_unknown_request(store):
    from test_model_proxy import provider

    from roami_agent.improvement.integrations.measurements import MeteredModel

    proxy, _ = proxy_for(store, limit=1)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, text="fixture upstream failure")

    async def no_delay(seconds):
        pass

    upstream = provider(proxy, handler)
    upstream.max_retries = 1
    upstream.sleep = no_delay
    budget = EpisodeBudget({"tokens": 1, "requests": 1, "seconds": 10}, shared_daily_limit=True)
    journal = []
    try:
        with pytest.raises(DomainError, match="MODEL_PROXY_USAGE_UNKNOWN"):
            await consume(MeteredModel(upstream, budget, "main", output_cap=0, journal=journal))
        assert len(calls) == 1 and budget.unknown
        assert budget.metrics()["tokens"] is None
        assert not journal[-1].get("admission_rejected", False)
        summary = await proxy.billing.daily_summary()
        assert summary["requests"] == 1 and summary["unknown"] == 1
    finally:
        await upstream.close()


@pytest.mark.parametrize("prices", [False, True])
async def test_shared_daily_admission_allows_known_zero_cost_without_token_usage(store, prices):
    from roami_agent.improvement.integrations.measurements import MeteredModel

    proxy, _ = proxy_for(store, limit=1, prices=prices)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b'data: {"choices":[{"delta":{"content":"done"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
        )

    from test_model_proxy import provider

    model = provider(proxy, handler)
    budget = EpisodeBudget({"tokens": 1, "requests": 1, "seconds": 20}, shared_daily_limit=True)
    metered = MeteredModel(model, budget, "main", output_cap=0)
    try:
        await consume(metered)
        if prices:
            with pytest.raises(DomainError, match="MODEL_PROXY_USAGE_UNKNOWN"):
                await consume(metered)
        else:
            await consume(metered)
        assert len(calls) == (1 if prices else 2)
        assert budget.unknown and budget.metrics()["tokens"] is None
        summary = await proxy.billing.daily_summary()
        assert summary["unknown"] == (1 if prices else 0)
        assert summary["requests"] == len(calls)
    finally:
        await model.close()
