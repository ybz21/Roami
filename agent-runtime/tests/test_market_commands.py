"""CLI and Agent marketplace installation uses pinned previews and existing policy."""

import base64
import copy
import json
from pathlib import Path

import httpx
import pytest
from test_professional_capabilities import prepared
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.server import market_catalogs
from roami_agent.server.http import create_app


def fixture_entry(kind="skills"):
    entry = {
        "name": "downloaded",
        "origin": {
            "source": "skills-sh",
            "id": "owner/repo/flow",
            "version": "a" * 40,
            "url": "https://github.com/owner/repo",
        },
    }
    if kind == "skills":
        entry.update(
            description="Workflow",
            text="pinned instructions\n" * 500,
            files={"references/guide.md": base64.b64encode(b"retained guide").decode()},
        )
    elif kind == "mcp":
        entry["config"] = {"transport": "sse", "url": "https://example.test/sse"}
    else:
        entry.update(argv=["python3", "--version"])
    return entry


def fake_catalog(monkeypatch, kind="skills"):
    entry = fixture_entry(kind)

    async def preview(*_):
        return {
            "kind": kind,
            "options": [{"label": "Pinned option", "entry": copy.deepcopy(entry)}],
        }

    async def search(*_):
        return {"items": [{"id": "owner/repo/flow", "name": "downloaded", "version": ""}]}

    monkeypatch.setattr(market_catalogs, "preview", preview)
    monkeypatch.setattr(market_catalogs, "search", search)
    return entry


def wire(verb, args):
    return {
        "function": {
            "name": "bash",
            "arguments": json.dumps(
                {
                    "argv": [
                        "roami",
                        "agent",
                        "capability",
                        "market",
                        verb,
                        "--input",
                        json.dumps(args),
                    ]
                }
            ),
        }
    }


async def test_native_agent_discovers_searches_reviews_and_installs_the_pinned_skill(
    store, monkeypatch
):
    expected = fake_catalog(monkeypatch)
    runtime = Runtime(store, ConversationModel())
    binding = {"owner": "local"}
    try:
        discovered = runtime.tools.directory.list("市场安装", "cli", 10, "main")["items"]
        assert any("market_install" in item.get("searchTerms", []) for item in discovered)
        searched = await runtime.tools.invoke(
            wire("search", {"source": "skills-sh", "query": "workflow"}), "main", binding
        )
        assert searched["items"][0]["id"] == "owner/repo/flow"
        args = {"source": "skills-sh", "id": "owner/repo/flow", "version": ""}
        preview = await runtime.tools.invoke(wire("preview", args), "main", binding)
        assert not runtime.capability_imports.saved["skills"]
        assert preview["options"][0]["entry"]["textTruncated"] is True
        assert "files" not in preview["options"][0]["entry"]
        assert preview["options"][0]["files"] == ["references/guide.md"]
        install = wire("install", {"previewId": preview["previewId"], "option": 0})
        assert runtime.tools.validate(install, "main")[0].effect == "write"
        result = await runtime.tools.invoke(install, "main", binding)
        assert result["state"] == "installed" and result["location"] == "skill://downloaded"
        saved = runtime.capability_imports.saved["skills"]["downloaded"]
        assert saved == expected and len(saved["text"]) > 8000
        package = Path(runtime.tools.skills["downloaded"]["packagePath"])
        assert (package / "references/guide.md").read_text() == "retained guide"
        assert await runtime.tools.invoke(install, "main", binding) == result
        for role in ("worker", "research"):
            assert await runtime.tools.invoke(install, role, binding) == result
        runtime.capability_imports.saved["skills"]["downloaded"]["text"] = "edited"
        with pytest.raises(DomainError, match="MARKET_INSTALL_CHANGED"):
            await runtime.tools.invoke(install, "main", binding)
    finally:
        await runtime.close()


@pytest.mark.parametrize("kind", ["mcp", "cli"])
async def test_market_package_types_register_without_executing_and_retry_exactly(
    store, monkeypatch, kind
):
    fake_catalog(monkeypatch, kind)
    runtime = Runtime(store, ConversationModel())
    try:
        operations = runtime.capability_markets.installations
        preview = await operations.prepare(
            "local", {"source": "skills-sh", "id": "owner/repo/flow", "version": ""}
        )
        args = {"previewId": preview["previewId"], "option": 0}
        result = await operations.install("local", args)
        assert await operations.install("local", args) == result
        assert runtime.capability_imports.saved[kind]["downloaded"]
        if kind == "mcp":
            assert result["connected"] is False
            assert runtime.mcp.connections["downloaded"].task is None
    finally:
        await runtime.close()


@pytest.mark.parametrize("condition", ["expired", "disabled", "changed", "owner", "option"])
async def test_installation_revalidates_source_owner_preview_and_option(
    store, monkeypatch, condition
):
    fake_catalog(monkeypatch)
    runtime = Runtime(store, ConversationModel())
    try:
        markets = runtime.capability_markets
        operations = markets.installations
        preview = await operations.prepare(
            "local", {"source": "skills-sh", "id": "owner/repo/flow", "version": ""}
        )
        args, owner = {"previewId": preview["previewId"], "option": 0}, "local"
        if condition == "expired":
            operations.receipts[preview["previewId"]]["until"] = 0
        elif condition == "disabled":
            markets.sources[0]["enabled"] = False
        elif condition == "changed":
            markets.sources[0]["url"] = "https://another.example.test"
        elif condition == "owner":
            owner = "other"
        else:
            args["option"] = True
        with pytest.raises(DomainError):
            await operations.install(owner, args)
        assert not runtime.capability_imports.saved["skills"]
    finally:
        await runtime.close()


async def test_conflicting_name_preserves_preview_and_source_change_during_download_is_rejected(
    store, monkeypatch
):
    fake_catalog(monkeypatch)
    runtime = Runtime(store, ConversationModel())
    try:
        operations = runtime.capability_markets.installations
        query = {"source": "skills-sh", "id": "owner/repo/flow", "version": ""}
        preview = await operations.prepare("local", query)
        await runtime.capability_imports.save(
            "local", "skills", {"name": "downloaded", "text": "existing"}
        )
        with pytest.raises(DomainError):
            await operations.install("local", {"previewId": preview["previewId"], "option": 0})
        result = await operations.install(
            "local", {"previewId": preview["previewId"], "option": 0, "name": "renamed"}
        )
        assert result["name"] == "renamed"
        runtime.capability_markets.cache.clear()

        async def changed(*_):
            runtime.capability_markets.sources[0]["url"] = "https://changed.example.test"
            return {"kind": "skills", "options": [{"label": "x", "entry": fixture_entry()}]}

        monkeypatch.setattr(market_catalogs, "preview", changed)
        with pytest.raises(DomainError, match="MARKET_SOURCE_CHANGED"):
            await operations.prepare("local", query)
    finally:
        await runtime.close()


async def test_professional_task_can_search_and_install_through_its_signed_context(
    store, monkeypatch
):
    fake_catalog(monkeypatch)
    runtime, _, _, context = await prepared(store)
    try:
        bridge = runtime.professional_capabilities

        def request(arguments, ident):
            return {"executionContext": context, "requestId": ident, "arguments": arguments}

        preview = await bridge.call(
            "market_preview",
            request({"source": "skills-sh", "id": "owner/repo/flow", "version": ""}, "preview"),
            "local",
        )
        result = await bridge.call(
            "market_install",
            request({"previewId": preview["result"]["previewId"], "option": 0}, "install"),
            "local",
        )
        assert result["state"] == "succeeded" and "downloaded" in runtime.tools.skills
    finally:
        await runtime.close()


async def test_market_cli_http_install_and_owner_fence(store, monkeypatch):
    fake_catalog(monkeypatch)
    runtime = Runtime(store, ConversationModel())
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
            base_url="http://agent",
        ) as client:
            args = {"source": "skills-sh", "id": "owner/repo/flow", "version": ""}
            assert (
                await client.post(
                    "/v1/capability-markets/prepare", headers={"X-Roami-Owner": "other"}, json=args
                )
            ).status_code == 403
            preview = await client.post(
                "/v1/capability-markets/prepare", headers={"X-Roami-Owner": "local"}, json=args
            )
            result = await client.post(
                "/v1/capability-markets/install",
                headers={"X-Roami-Owner": "local"},
                json={"previewId": preview.json()["data"]["previewId"], "option": 0},
            )
            assert result.status_code == 200 and result.json()["data"]["state"] == "installed"
    finally:
        await runtime.close()
