import asyncio
import json
from dataclasses import replace
from itertools import pairwise

import httpx
import pytest
from test_improvement_workflow import setup
from test_model_proxy import EVENTS, consume, proxy_for

from roami_agent.app import configured_provider
from roami_agent.improvement.integrations.codex_proxy import CodexProxy
from roami_agent.improvement.integrations.measurements import EpisodeBudget
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.model_routes import settings_with_route
from roami_agent.providers.model_proxy import model_accounting
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


async def test_rsi_provider_ignores_legacy_python_token_and_spending_limits(store):
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
        model = proxy.attach(model, "worker")
        await consume(model)
        await consume(model)
        await model.close()
    assert len(requests) == 2
    summary = await proxy.billing.daily_summary()
    assert summary["charges"] == [{"currency": "USD", "amount": "0.00416"}]
    assert summary["requests"] == 2


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
    summary = await proxy.billing.view(days=1)
    assert summary["pending"] == summary["unknown"] == 0
    assert summary["recent"][0]["cost_source"] == "not_sent"


async def test_waiting_research_uses_the_shared_billing_day_without_a_new_token_budget_row(
    store, tmp_path
):
    workflow, _config, *_ = await setup(tmp_path)
    proxy, _ = proxy_for(store, limit=1)
    workflow.model_proxy = proxy
    timestamp = [1793030400000]
    workflow.clock = lambda: timestamp[0]
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
        with pytest.raises(DomainError, match="MODEL_HTTP_503"):
            await consume(MeteredModel(upstream, budget, "main", output_cap=0, journal=journal))
        assert len(calls) == 2 and budget.unknown
        assert budget.metrics()["tokens"] is None
        assert not journal[-1].get("admission_rejected", False)
        summary = await proxy.billing.daily_summary()
        assert summary["requests"] == 2 and summary["unknown"] == 2
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
        await consume(metered)
        assert len(calls) == 2
        assert budget.unknown and budget.metrics()["tokens"] is None
        summary = await proxy.billing.daily_summary()
        assert summary["unknown"] == (2 if prices else 0)
        assert summary["requests"] == len(calls)
    finally:
        await model.close()
