"""Codex Responses traffic uses the same admission lock and fee ledger as chat."""

import json

import httpx
import pytest
from test_model_proxy import Chunks, consume, provider, proxy_for

from roami_agent.improvement.integrations.codex_proxy import CodexProxy, codex_route
from roami_agent.protocol.errors import DomainError
from roami_agent.providers.model_billing import usage_counts


def events(*, complete=True, charged=True):
    usage = {
        "input_tokens": 100,
        "output_tokens": 20,
        "input_tokens_details": {"cached_tokens": 30},
    }
    if charged:
        usage.update(cost=0.01, currency="USD")
    value = {
        "type": "response.completed" if complete else "response.in_progress",
        "response": {"status": "completed" if complete else "in_progress", "usage": usage},
    }
    return ("data: " + json.dumps(value) + "\n\n").encode()


def test_responses_usage_does_not_double_count_cached_tokens():
    assert usage_counts(
        {"input_tokens": 100, "output_tokens": 20, "input_tokens_details": {"cached_tokens": 30}}
    ) == (100, 20, 30)
    assert (
        usage_counts(
            {
                "input_tokens": 100,
                "output_tokens": 20,
                "input_tokens_details": {"cached_tokens": 101},
            }
        )
        is None
    )


async def test_codex_charges_share_daily_admission_with_main_chat(store):
    proxy, _ = proxy_for(store, limit=0.005)
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url == "https://fixture.invalid/v1/responses"
        assert request.headers["authorization"] == "Bearer fixture-private"
        assert "x-roami-rsi-key" not in request.headers
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=Chunks(events())
        )

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with CodexProxy(
        proxy, "https://fixture.invalid/v1", "review", "fixture-codex", upstream_client=upstream
    ) as bridge:
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.post(
                bridge.url + "/responses",
                headers={
                    "X-Roami-Rsi-Key": bridge.secret,
                    "Authorization": "Bearer fixture-private",
                },
                json={"input": "fixture"},
            )
            assert response.status_code == 200 and response.content == events()
        view = await proxy.billing.view()
        assert view["charges"] == [{"currency": "USD", "amount": "0.01"}]
        assert view["recent"][0]["role"] == "rsi_codex_review"
        assert view["recent"][0]["input_tokens"] == 100
        model = provider(
            proxy, lambda request: pytest.fail("Daily limit must reject before chat's network call")
        )
        try:
            with pytest.raises(DomainError, match="MODEL_PROXY_DAILY_LIMIT"):
                await consume(model)
        finally:
            await model.close()
    assert len(requests) == 1


async def test_untrusted_loopback_request_cannot_spend_or_forward_credentials(store):
    proxy, _ = proxy_for(store, limit=1)
    upstream = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: pytest.fail("Unauthorized request reached upstream")
        )
    )
    async with (
        CodexProxy(
            proxy, "https://fixture.invalid/v1", "review", "fixture", upstream_client=upstream
        ) as bridge,
        httpx.AsyncClient(trust_env=False) as client,
    ):
        response = await client.post(bridge.url + "/responses", json={"input": "x"})
        assert response.json()["error"]["code"] == "RSI_CODEX_PROXY_AUTH"
    assert (await proxy.billing.view())["requests"] == 0


@pytest.mark.parametrize(("complete", "charged"), [(False, True), (True, False)])
@pytest.mark.parametrize("priced", [False, True])
async def test_codex_missing_receipt_uses_zero_default_or_configured_prices(
    store, complete, charged, priced
):
    proxy, _ = proxy_for(store, limit=1, prices=priced)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=Chunks(events(complete=complete, charged=charged)),
        )

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with (
        CodexProxy(
            proxy, "https://fixture.invalid/v1", "review", "fixture", upstream_client=upstream
        ) as bridge,
        httpx.AsyncClient(trust_env=False) as client,
    ):
        headers = {"X-Roami-Rsi-Key": bridge.secret}
        assert (
            await client.post(bridge.url + "/responses", json={"input": "x"}, headers=headers)
        ).status_code == 200
        response = await client.post(
            bridge.url + "/responses", json={"input": "x"}, headers=headers
        )
        blocked = priced and not complete
        if blocked:
            assert response.json()["error"]["code"] == "MODEL_PROXY_USAGE_UNKNOWN"
        else:
            assert response.status_code == 200
    view = await proxy.billing.view()
    assert len(requests) == (1 if blocked else 2)
    assert view["unknown"] == int(blocked)
    if not priced:
        assert view["charges"] == [{"currency": "USD", "amount": "0"}]


async def test_route_is_ephemeral_and_keeps_original_settings_unmodified(store):
    proxy, _ = proxy_for(store)
    selected = {
        "model": "fixture",
        "model_provider": "fixture",
        "model_providers.fixture.base_url": "https://fixture.invalid/v1",
        "model_providers.fixture.env_key": "RSI_TEST_KEY",
    }
    env = {"RSI_TEST_KEY": "fixture-private"}
    async with codex_route(proxy, selected, env, "review") as (routed, environment):
        assert routed["model_providers.fixture.base_url"].startswith("http://127.0.0.1:")
        assert (
            routed["model_providers.fixture.env_http_headers"]["X-Roami-Rsi-Key"]
            == "ROAMI_RSI_CODEX_PROXY_KEY"
        )
        assert environment["ROAMI_RSI_CODEX_PROXY_KEY"]
    assert selected["model_providers.fixture.base_url"] == "https://fixture.invalid/v1"
    assert "ROAMI_RSI_CODEX_PROXY_KEY" not in env


async def test_terminal_failed_response_keeps_its_actual_charge_receipt(store):
    proxy, _ = proxy_for(store, limit=0.005)
    body = (
        events()
        .replace(b"response.completed", b"response.failed")
        .replace(b'"status": "completed"', b'"status": "failed"')
    )
    upstream = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=Chunks(body)
            )
        )
    )
    async with (
        CodexProxy(
            proxy, "https://fixture.invalid/v1", "review", "fixture", upstream_client=upstream
        ) as bridge,
        httpx.AsyncClient(trust_env=False) as client,
    ):
        response = await client.post(
            bridge.url + "/responses",
            json={"input": "x"},
            headers={"X-Roami-Rsi-Key": bridge.secret},
        )
        assert response.status_code == 200
        assert bridge.outcome["attempts"] == 1
    view = await proxy.billing.view()
    assert view["charges"] == [{"currency": "USD", "amount": "0.01"}] and view["unknown"] == 0
