import asyncio
import gzip
import json
from datetime import UTC, datetime

import httpx
import pytest

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.providers.chat_completions import ChatCompletions
from roami_agent.providers.model_billing import cost_nano, proxy_configuration, usage_counts
from roami_agent.providers.model_proxy import ModelProxy
from roami_agent.server.configuration import Settings
from roami_agent.server.http import create_app
from roami_agent.server.model_settings import settings_path

PRICES = {"input": 2, "output": 8, "cacheRead": 0.2}
USAGE = {
    "prompt_tokens": 1000,
    "completion_tokens": 100,
    "prompt_tokens_details": {"cached_tokens": 400},
}
EVENTS = (
    'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":"stop"}]}\n\ndata: '
    + json.dumps({"choices": [], "usage": USAGE})
    + "\n\ndata: [DONE]\n\n"
).encode()


class Chunks(httpx.AsyncByteStream):
    def __init__(self, body, gate=None):
        self.body, self.gate = body, gate

    async def __aiter__(self):
        if self.gate:
            await self.gate.wait()
        for start in range(0, len(self.body), 13):
            yield self.body[start : start + 13]


def provider(proxy, handler, role="main"):
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return proxy.attach(
        ChatCompletions("http://127.0.0.1/v1", "fixture", client=upstream, max_retries=0), role
    )


def proxy_for(store, *, limit=None, prices=True):
    config = {"dailyLimit": limit, "prices": {"fixture": dict(PRICES)} if prices else {}}
    return ModelProxy(store, lambda: config, lambda: "Asia/Shanghai"), config


async def consume(model):
    return [
        event async for event in model.stream([{"role": "user", "content": "private prompt"}], [])
    ]


def test_cache_tokens_are_not_charged_twice_and_cost_is_fixed_precision():
    assert cost_nano(PRICES, usage_counts(USAGE)) == 2_080_000
    assert cost_nano({"input": 0.000001, "output": 0, "cacheRead": 0}, (1, 0, 0)) == 1
    assert usage_counts({**USAGE, "prompt_tokens_details": {"cached_tokens": 1001}}) is None
    assert usage_counts({**USAGE, "prompt_tokens": True}) is None


@pytest.mark.parametrize(
    "raw",
    [
        {"dailyLimit": 0},
        {"dailyLimit": -1},
        {"dailyLimit": True},
        {"dailyLimit": float("nan")},
        {"dailyLimit": "2"},
        {"dailyLimit": 0.0000001},
        {"prices": []},
        {"prices": {"fixture": {"input": 1}}},
        {"prices": {"fixture": {**PRICES, "output": -1}}},
        {"prices": {"fixture": {**PRICES, "output": float("inf")}}},
        {"enabled": True},
    ],
)
def test_invalid_billing_configuration_is_rejected(raw):
    with pytest.raises(DomainError, match="INVALID_MODEL_PROXY_CONFIG"):
        proxy_configuration(raw)


@pytest.mark.parametrize("compressed", [False, True])
async def test_fragmented_stream_preserves_content_and_settles_once(store, compressed):
    proxy, config = proxy_for(store)
    body = gzip.compress(EVENTS) if compressed else EVENTS
    headers = {
        "content-type": "text/event-stream",
        **({"content-encoding": "gzip"} if compressed else {}),
    }
    model = provider(
        proxy, lambda request: httpx.Response(200, headers=headers, stream=Chunks(body))
    )
    events = await consume(model)
    assert [event.value for event in events if event.kind == "text"] == ["hello"]
    await model.close()
    usage = await proxy.billing.view()
    assert usage["requests"] == 1 and usage["unknown"] == usage["pending"] == 0
    assert usage["knownCost"] == 0.00208 and usage["cacheReadTokens"] == 400
    rows = await store.call(
        lambda db: [dict(row) for row in db.execute("SELECT * FROM model_proxy_calls")]
    )
    assert "private prompt" not in json.dumps(rows)
    config["prices"]["fixture"]["input"] = 900
    assert (await proxy.billing.view())["knownCost"] == usage["knownCost"]


async def test_price_snapshot_idempotence_and_recovery_survive_new_proxy(store):
    proxy, config = proxy_for(store)
    await proxy.ready()
    call, rates = await proxy.billing.admit("worker", "fixture")
    config["prices"] = {}
    await proxy.billing.settle(call, rates, (1000, 100, 400))
    await proxy.billing.settle(call, rates, (999999, 100, 0))
    pending, _ = await proxy.billing.admit("main", "fixture")
    recovered, _ = proxy_for(store)
    await recovered.ready()
    usage = await recovered.billing.view()
    assert usage["knownCost"] == 0.00208 and usage["unknown"] == 1 and usage["pending"] == 0
    assert next(row for row in usage["recent"] if row["id"] == pending)["state"] == "unknown"


async def test_daily_limit_blocks_before_network_and_resets_in_node_timezone(store):
    proxy, _ = proxy_for(store, limit=0.002)
    proxy.billing.clock = lambda: int(datetime(2026, 10, 25, 15, 59, tzinfo=UTC).timestamp() * 1000)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=EVENTS)

    model = provider(proxy, handler)
    await consume(model)
    with pytest.raises(DomainError, match="MODEL_PROXY_DAILY_LIMIT"):
        await consume(model)
    assert len(requests) == 1
    proxy.billing.clock = lambda: int(datetime(2026, 10, 25, 16, 1, tzinfo=UTC).timestamp() * 1000)
    assert (await proxy.billing.view())["day"] == "2026-10-26"
    await consume(model)
    assert len(requests) == 2
    await model.close()


async def test_limited_main_and_worker_admissions_are_serialized(store):
    proxy, _ = proxy_for(store, limit=0.001)
    started, release = asyncio.Event(), asyncio.Event()
    requests = []

    def handler(request):
        requests.append(request)
        started.set()
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=Chunks(EVENTS, release)
        )

    main, worker = provider(proxy, handler), provider(proxy, handler, "worker")
    first = asyncio.create_task(consume(main))
    await started.wait()
    second = asyncio.create_task(consume(worker))
    await asyncio.sleep(0)
    assert len(requests) == 1
    release.set()
    await first
    with pytest.raises(DomainError, match="MODEL_PROXY_DAILY_LIMIT"):
        await second
    assert len(requests) == 1
    await main.close()
    await worker.close()


@pytest.mark.parametrize(
    "body",
    [
        b'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
        EVENTS.replace(b"data: [DONE]\n\n", b""),
    ],
)
async def test_missing_usage_or_truncated_stream_is_unknown_and_blocks_limited_calls(store, body):
    proxy, _ = proxy_for(store, limit=10)
    model = provider(
        proxy,
        lambda request: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=body
        ),
    )
    await consume(model)
    usage = await proxy.billing.view()
    assert usage["unknown"] == 1 and usage["recent"][0]["cost"] is None
    with pytest.raises(DomainError, match="MODEL_PROXY_USAGE_UNKNOWN"):
        await consume(model)
    await model.close()


async def test_unpriced_model_is_unknown_without_limit_and_refused_with_limit(store):
    proxy, config = proxy_for(store, prices=False)
    model = provider(
        proxy,
        lambda request: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=EVENTS
        ),
    )
    await consume(model)
    usage = await proxy.billing.view()
    assert usage["unknown"] == 1 and usage["inputTokens"] == 1000
    config["dailyLimit"] = 1
    with pytest.raises(DomainError, match="MODEL_PROXY_PRICE_REQUIRED"):
        await consume(model)
    await model.close()


async def test_rejected_attempt_and_retry_have_independent_receipts(store):
    proxy, _ = proxy_for(store)
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return (
            httpx.Response(503, text="private error body")
            if calls == 1
            else httpx.Response(200, headers={"content-type": "text/event-stream"}, content=EVENTS)
        )

    model = provider(proxy, handler)
    model.max_retries, model.sleep = 1, lambda _: asyncio.sleep(0)
    await consume(model)
    usage = await proxy.billing.view()
    assert usage["requests"] == 2 and usage["knownCost"] == 0.00208
    assert {row["state"] for row in usage["recent"]} == {"failed", "known"}
    assert "private error body" not in json.dumps(usage)
    await model.close()


async def test_cancelled_stream_releases_admission_but_keeps_unknown_charge(store):
    proxy, _ = proxy_for(store, limit=1)
    started, release = asyncio.Event(), asyncio.Event()

    def handler(request):
        started.set()
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=Chunks(EVENTS, release)
        )

    model = provider(proxy, handler)
    pending = asyncio.create_task(consume(model))
    await started.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not proxy.admission.locked()
    usage = await proxy.billing.view()
    assert usage["unknown"] == 1 and usage["pending"] == 0
    await model.close()


async def test_settings_http_owner_boundary_persistence_and_invalid_save(store):
    class EmptyModel:
        async def stream(self, messages, tools):
            return
            yield

    runtime = Runtime(
        store,
        EmptyModel(),
        settings=Settings(endpoint="http://127.0.0.1:1/v1", model="fixture", context_window=32000),
    )
    transport = httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://private", headers={"X-Roami-Owner": "local"}
    ) as client:
        config = {"dailyLimit": 10, "prices": {"fixture": PRICES}}
        saved = await client.put("/v1/model-settings", json={"proxy": config})
        assert saved.status_code == 200 and saved.json()["data"]["proxy"] == config
        before = settings_path(store.data_root).read_bytes()
        invalid = await client.put("/v1/model-settings", json={"proxy": {"dailyLimit": -2}})
        assert invalid.status_code == 400 and settings_path(store.data_root).read_bytes() == before
        assert (await client.get("/v1/model-usage")).json()["data"]["requests"] == 0
        assert (
            await client.get("/v1/model-usage", headers={"X-Roami-Owner": "other"})
        ).status_code == 403
    await runtime.close()


async def test_disk_reopen_preserves_receipts_and_marks_inflight_unknown(store):
    from roami_agent.storage.database import Database

    proxy, _ = proxy_for(store)
    await proxy.ready()
    known, rates = await proxy.billing.admit("main", "fixture")
    await proxy.billing.settle(known, rates, (1000, 100, 400))
    await proxy.billing.admit("worker", "fixture")
    await store.close()
    reopened = Database(store.path, store.data_root, managed=False)
    await reopened.open()
    try:
        restored, _ = proxy_for(reopened, limit=10)
        await restored.ready()
        usage = await restored.billing.view()
        assert usage["requests"] == 2 and usage["knownCost"] == 0.00208
        assert usage["unknown"] == 1 and usage["pending"] == 0
        with pytest.raises(DomainError, match="MODEL_PROXY_USAGE_UNKNOWN"):
            await restored.billing.admit("main", "fixture")
    finally:
        await reopened.close()


async def test_cancellation_during_admission_never_sends_or_leaves_pending(store, monkeypatch):
    proxy, _ = proxy_for(store, limit=1)
    entered, release = asyncio.Event(), asyncio.Event()
    admit = proxy.billing.admit

    async def delayed(role, model):
        entered.set()
        await release.wait()
        return await admit(role, model)

    monkeypatch.setattr(proxy.billing, "admit", delayed)
    model = provider(proxy, lambda request: pytest.fail("cancelled admission reached upstream"))
    pending = asyncio.create_task(consume(model))
    await entered.wait()
    pending.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    usage = await proxy.billing.view()
    assert not proxy.admission.locked()
    assert usage["requests"] == 1 and usage["unknown"] == usage["pending"] == 0
    assert usage["recent"][0]["state"] == "failed"
    await model.close()
