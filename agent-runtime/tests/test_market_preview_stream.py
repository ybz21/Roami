import asyncio
import base64
import json

import httpx
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.server import market_catalogs
from roami_agent.server.http import create_app
from roami_agent.server.market_preview_stream import preview_stream

PAYLOAD = {"source": "skills-sh", "id": "owner/repo/workflow", "version": ""}


async def next_event(stream):
    return json.loads(await asyncio.wait_for(anext(stream), timeout=2))


async def test_document_and_images_arrive_before_slow_files_and_no_receipt_is_issued_early(
    store, monkeypatch
):
    monkeypatch.delenv("VERCEL_OIDC_TOKEN", raising=False)
    files_ready, images_ready = asyncio.Event(), asyncio.Event()
    commit = "a" * 40
    text = "# Workflow\n![Effect](https://raw.githubusercontent.com/o/r/main/hero.png)"

    async def fetch(url, **kwargs):
        if url.endswith("/commits/HEAD"):
            return {"sha": commit}
        if "/git/trees/" in url:
            return {
                "tree": [
                    {"path": "skills/workflow/" + name, "type": "blob", "mode": "100644"}
                    for name in ["SKILL.md", "reference.md"]
                ]
            }
        if "/contents/" in url:
            await images_ready.wait()
            raw = b"\x89PNG\r\n\x1a\nimage"
            return {
                "type": "file",
                "size": len(raw),
                "encoding": "base64",
                "content": base64.b64encode(raw).decode(),
            }
        if url.endswith("SKILL.md"):
            return text.encode()
        await files_ready.wait()
        return b"Reference"

    monkeypatch.setattr(market_catalogs, "fetch", fetch)
    markets = Runtime(store, ConversationModel()).capability_markets
    stream = preview_stream(markets, "local", PAYLOAD)
    assert (await next_event(stream))["type"] == "loading"
    document = await next_event(stream)
    assert document["type"] == "document" and document["entry"]["text"] == text
    assert not markets.installations.receipts
    images_ready.set()
    assert (await next_event(stream))["type"] == "images"
    assert not markets.installations.receipts
    files_ready.set()
    assert (await next_event(stream))["type"] == "files"
    ready = await next_event(stream)
    assert ready["type"] == "ready"
    assert ready["data"]["previewId"] in markets.installations.receipts
    await stream.aclose()


async def test_progress_is_replayed_to_a_shared_request_and_disconnect_does_not_cancel_it(
    store, monkeypatch
):
    ready, calls = asyncio.Event(), []

    async def preview(*args):
        calls.append(1)
        entry = {"name": "workflow", "text": "# Instructions"}
        market_catalogs.report("document", entry=entry)
        await ready.wait()
        return {"kind": "skills", "options": [{"label": "workflow", "entry": entry}]}

    monkeypatch.setattr(market_catalogs, "preview", preview)
    markets = Runtime(store, ConversationModel()).capability_markets
    first = preview_stream(markets, "local", PAYLOAD)
    await next_event(first)
    assert (await next_event(first))["type"] == "document"
    second = preview_stream(markets, "local", PAYLOAD)
    await next_event(second)
    assert (await next_event(second))["type"] == "document"
    await first.aclose()
    ready.set()
    assert (await next_event(second))["type"] == "ready"
    await second.aclose()
    assert calls == [1] and not markets.listeners


async def test_http_stream_reports_invalid_payload_without_a_receipt(store):
    runtime = Runtime(store, ConversationModel())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://runtime",
        headers={"X-Roami-Owner": "local"},
    ) as client:
        response = await client.post(
            "/v1/capability-markets/preview",
            headers={"Accept": "application/x-ndjson"},
            json={**PAYLOAD, "id": ""},
        )
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1] == {"type": "error", "error": {"code": "INVALID_MARKET_QUERY"}}
    assert not runtime.capability_markets.installations.receipts


async def test_failed_bundle_preserves_document_event_without_issuing_install_receipt(
    store, monkeypatch
):
    async def preview(*args):
        market_catalogs.report("document", entry={"name": "workflow", "text": "# Readable"})
        raise DomainError("INVALID_SKILL_PACKAGE")

    monkeypatch.setattr(market_catalogs, "preview", preview)
    markets = Runtime(store, ConversationModel()).capability_markets
    stream = preview_stream(markets, "local", PAYLOAD)
    await next_event(stream)
    assert (await next_event(stream))["entry"]["text"] == "# Readable"
    assert (await next_event(stream)) == {
        "type": "error",
        "error": {"code": "INVALID_SKILL_PACKAGE"},
    }
    await stream.aclose()
    assert not markets.installations.receipts and not markets.listeners
