import asyncio

import httpx
import pytest

from roami_agent.protocol.errors import DomainError
from roami_agent.server import market_catalogs


async def test_catalog_operation_reuses_client_without_forwarding_authorization(monkeypatch):
    clients, requests = [], []
    original = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    def client(**kwargs):
        instance = original(**kwargs, transport=httpx.MockTransport(respond))
        clients.append(instance)
        return instance

    monkeypatch.setattr(httpx, "AsyncClient", client)
    async with market_catalogs.connection():
        await market_catalogs.fetch(
            "https://skills.sh/api/v1/skills", headers={"Authorization": "Bearer test-oidc"}
        )
        await asyncio.gather(
            market_catalogs.fetch("https://api.github.com/repos/owner/repo"),
            market_catalogs.fetch("https://raw.githubusercontent.com/owner/repo/commit/SKILL.md"),
        )
        assert len(clients) == 1 and not clients[0].is_closed
    assert clients[0].is_closed
    assert requests[0].headers["Authorization"] == "Bearer test-oidc"
    assert all("Authorization" not in request.headers for request in requests[1:])
    await market_catalogs.fetch("https://skills.sh/api/skills/all-time/0")
    assert len(clients) == 2 and clients[1].is_closed


async def test_cancelled_catalog_operation_closes_client_and_does_not_reuse_it(monkeypatch):
    started, blocked = asyncio.Event(), asyncio.Event()
    clients = []
    original = httpx.AsyncClient

    async def respond(request):
        if request.url.path == "/blocked":
            started.set()
            await blocked.wait()
        return httpx.Response(200, json={"ok": True})

    def client(**kwargs):
        instance = original(**kwargs, transport=httpx.MockTransport(respond))
        clients.append(instance)
        return instance

    async def operation():
        async with market_catalogs.connection():
            await market_catalogs.fetch("https://api.github.com/blocked")

    monkeypatch.setattr(httpx, "AsyncClient", client)
    task = asyncio.create_task(operation())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert clients[0].is_closed
    assert await market_catalogs.fetch("https://api.github.com/next") == {"ok": True}
    assert len(clients) == 2 and clients[1].is_closed


async def test_failed_file_download_cancels_siblings_before_archive_fallback(monkeypatch):
    started, cancelled = asyncio.Event(), asyncio.Event()
    commit = "a" * 40

    async def fetch(url, **kwargs):
        if url.endswith("/commits/HEAD"):
            return {"sha": commit}
        if "/git/trees/" in url:
            return {
                "tree": [
                    {"path": "skills/workflow/" + name, "type": "blob", "mode": "100644"}
                    for name in ["SKILL.md", "script.py"]
                ]
            }
        if url.endswith("SKILL.md"):
            await started.wait()
            raise DomainError("MARKET_UNAVAILABLE", 502)
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def archive(owner, repo, skill, fetch, **kwargs):
        assert cancelled.is_set()
        assert kwargs == {"commit": commit}
        return "# Instructions", {}, commit

    monkeypatch.setattr(market_catalogs, "fetch", fetch)
    monkeypatch.setattr(market_catalogs, "download_archive", archive)
    entry, version = await market_catalogs.skill_entry("owner/repo/workflow")
    assert entry["text"] == "# Instructions" and version == commit
