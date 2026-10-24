"""Market discovery stays read-only until a reviewed registration is saved."""

import asyncio
import base64
import copy
import json
import os
import sys
from pathlib import Path

import httpx
import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.server import market_catalogs
from roami_agent.server.capability_imports import CapabilityImports
from roami_agent.server.configuration import Settings
from roami_agent.server.http import create_app


async def test_source_configuration_restart_isolation_and_failed_write(store, monkeypatch):
    runtime = Runtime(store, ConversationModel())
    markets = runtime.capability_markets
    sources = markets.view("local")["sources"]
    sources[0]["enabled"] = False
    sources.append(
        {**sources[1], "id": "team", "name": "Team", "url": "https://registry.example.test"}
    )
    await markets.save("local", {"sources": sources})
    assert os.stat(markets.path).st_mode & 0o777 == 0o600
    restored = Runtime(store, ConversationModel()).capability_markets
    assert restored.view("local")["sources"] == sources
    with pytest.raises(DomainError, match="MARKET_SOURCE_DISABLED"):
        await restored.search("local", "skills-sh", "react")
    with pytest.raises(DomainError, match="FORBIDDEN"):
        restored.view("other")
    with pytest.raises(DomainError, match="FORBIDDEN"):
        await restored.search("other", "npm", "cli")
    before = markets.path.read_bytes()
    monkeypatch.setattr(os, "replace", lambda *_: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        await markets.save("local", {"sources": sources[:-1]})
    assert markets.path.read_bytes() == before
    assert markets.view("local")["sources"] == sources


@pytest.mark.parametrize(
    "patch",
    [
        {"url": "http://registry.example.test"},
        {"url": "https://u:p@example.test"},
        {"url": "https://example.test?token=secret"},
        {"provider": []},
        {"enabled": 1},
        {"id": "bad/id"},
    ],
)
async def test_rejects_invalid_sources_without_persisting(store, patch):
    markets = Runtime(store, ConversationModel()).capability_markets
    sources = markets.view("local")["sources"]
    sources[0].update(patch)
    with pytest.raises(DomainError, match="INVALID_MARKET_SOURCE"):
        await markets.save("local", {"sources": sources})
    assert not markets.path.exists()


async def test_search_merges_inflight_caches_and_rechecks_disabled_source(store, monkeypatch):
    runtime = Runtime(store, ConversationModel())
    calls = []

    async def search(source, query, cursor):
        calls.append(query)
        await asyncio.sleep(0.01)
        return {"items": [{"id": "example"}], "nextCursor": ""}

    monkeypatch.setattr(market_catalogs, "search", search)
    markets = runtime.capability_markets
    first, second = await asyncio.gather(
        markets.search("local", "npm", "format"), markets.search("local", "npm", "format")
    )
    first["items"].clear()
    assert second["items"]
    assert (await markets.search("local", "npm", "format"))["items"]
    assert calls == ["format"]
    sources = markets.view("local")["sources"]
    sources[-1]["enabled"] = False
    await markets.save("local", {"sources": sources})
    with pytest.raises(DomainError, match="MARKET_SOURCE_DISABLED"):
        await markets.search("local", "npm", "format")


async def test_registry_pagination_status_and_transport_options(monkeypatch):
    seen = []
    server = {
        "name": "org.example/docs",
        "version": "1.0.0",
        "remotes": [
            {"type": "sse", "url": "https://example.test/sse"},
            {
                "type": "streamable-http",
                "url": "https://example.test/mcp",
                "headers": [{"name": "Authorization"}],
            },
        ],
        "packages": [
            {
                "registryType": "npm",
                "identifier": "docs-mcp",
                "version": "1.0.0",
                "environmentVariables": [{"name": "DOCS_TOKEN"}],
            }
        ],
    }

    async def fetch(url, **kwargs):
        seen.append((url, kwargs))
        if "/versions/" in url:
            return {"server": server}
        return {
            "servers": [
                {"server": server},
                {
                    "server": server,
                    "_meta": {"io.modelcontextprotocol.registry/official": {"status": "deleted"}},
                },
            ],
            "metadata": {"nextCursor": "next"},
        }

    monkeypatch.setattr(market_catalogs, "fetch", fetch)
    source = copy.deepcopy(market_catalogs.DEFAULT_SOURCES[1])
    result = await market_catalogs.search(source, "docs", "previous")
    assert len(result["items"]) == 1 and result["nextCursor"] == "next"
    assert seen[0][1]["params"]["cursor"] == "previous"
    result = await market_catalogs.preview(source, server["name"], server["version"])
    assert {item["entry"]["config"]["transport"] for item in result["options"]} == {
        "stdio",
        "sse",
        "streamable_http",
    }
    for item in result["options"]:
        CapabilityImports.validate("mcp", item["entry"])
    assert "org.example%2Fdocs" in seen[-1][0]


async def test_skill_download_preserves_pinned_revision_assets_and_runtime_policy(
    store, monkeypatch
):
    commit = "a" * 40
    contents = {
        "SKILL.md": b"---\nname: workflow\ndescription: Example\n---\nRead references/rules.md and run scripts/check.py.",
        "references/rules.md": b"# Rules\nVerify output.",
        "scripts/check.py": b"print('verified')",
        "assets/cover.bin": b"\x00\xff",
        "LICENSE": b"MIT",
    }
    urls = []

    async def fetch(url, **kwargs):
        urls.append(url)
        if url.endswith("/commits/HEAD"):
            return {"sha": commit}
        if "/git/trees/" in url:
            return {
                "tree": [
                    {
                        "path": "skills/workflow/" + path,
                        "mode": "100644",
                        "type": "blob",
                        "size": len(raw),
                    }
                    for path, raw in contents.items()
                ]
            }
        assert "/" + commit + "/" in url
        return contents[url.split("/skills/workflow/")[1]]

    monkeypatch.setattr(market_catalogs, "fetch", fetch)
    runtime = Runtime(store, ConversationModel())
    preview = await runtime.capability_markets.preview(
        "local", {"source": "skills-sh", "id": "publisher/repository/workflow", "version": ""}
    )
    assert not runtime.capability_imports.path.exists()
    entry = preview["options"][0]["entry"]
    assert entry["origin"]["version"] == commit
    await runtime.capability_imports.save("local", "skills", entry)
    skill = runtime.tools.skills["workflow"]
    assert (Path(skill["packagePath"]) / "assets/cover.bin").read_bytes() == b"\x00\xff"
    assert "references/rules.md" in skill["references"]
    wire = {
        "function": {
            "name": "read",
            "arguments": json.dumps({"path": "skill://workflow/references/rules.md"}),
        }
    }
    assert "Verify output" in (await runtime.tools.invoke(wire, "main", {}))["text"]
    restored = Runtime(store, ConversationModel())
    assert restored.tools.skills["workflow"]["packagePath"] == skill["packagePath"]
    await restored.capability_settings.save(
        "local", {"kind": "skills", "name": "workflow", "enabled": False}
    )
    with pytest.raises(DomainError, match="SKILL_DISABLED"):
        await restored.tools.invoke(wire, "main", {})


@pytest.mark.parametrize(
    "path", ["../escape.py", "/tmp/escape", "scripts/../escape", "scripts\\escape", "a//b"]
)
def test_package_rejects_path_escape(path):
    with pytest.raises(DomainError, match="INVALID_SKILL_PACKAGE"):
        CapabilityImports.validate(
            "skills",
            {
                "name": "workflow",
                "text": "Instructions",
                "files": {path: base64.b64encode(b"data").decode()},
            },
        )


async def test_npm_cli_pins_version_and_passes_arguments_without_shell(
    store, tmp_path, monkeypatch
):
    async def fetch(url, **kwargs):
        assert url.endswith("/formatter/1.2.3")
        return {"bin": {"format": "bin/format.js"}, "description": "Formatter"}

    monkeypatch.setattr(market_catalogs, "fetch", fetch)
    result = await market_catalogs.preview(market_catalogs.DEFAULT_SOURCES[2], "formatter", "1.2.3")
    entry = result["options"][0]["entry"]
    assert "--package=formatter@1.2.3" in entry["argv"]
    entry["argv"] = [sys.executable, "-c", "import json,sys; print(json.dumps(sys.argv[1:]))"]
    entry["cwd"] = str(tmp_path)
    runtime = Runtime(store, ConversationModel(), settings=Settings(shell_roots=(tmp_path,)))
    await runtime.capability_imports.save("local", "cli", entry)
    wire = {
        "function": {
            "name": "bash",
            "arguments": json.dumps(
                {
                    "argv": [
                        "roami",
                        "agent",
                        "capability",
                        "call",
                        "cli_format",
                        "--input",
                        json.dumps({"args": ["--version", "$(touch injected)"]}),
                    ]
                }
            ),
        }
    }
    assert json.loads((await runtime.tools.invoke(wire, "main", {}))["stdout"]) == [
        "--version",
        "$(touch injected)",
    ]
    await runtime.capability_settings.save(
        "local", {"kind": "tools", "name": "cli_format", "enabled": False}
    )
    with pytest.raises(DomainError, match="TOOL_DISABLED"):
        await runtime.tools.invoke(wire, "main", {})


@pytest.mark.parametrize("transport", ["stdio", "sse", "streamable_http", "http"])
def test_mcp_type_alias_is_preserved_and_conflicts_are_rejected(transport):
    config = {
        "type": transport,
        **({"command": "python3"} if transport == "stdio" else {"url": "https://example.test/mcp"}),
    }
    value = CapabilityImports.validate("mcp", {"name": "example", "config": config})
    assert value["config"]["transport"] == ("streamable_http" if transport == "http" else transport)
    with pytest.raises(DomainError, match="INVALID_MCP_CONFIG"):
        CapabilityImports.validate(
            "mcp", {"name": "example", "config": {**config, "transport": "other"}}
        )


async def test_market_http_requires_owner_and_returns_only_readable_errors(store, monkeypatch):
    runtime = Runtime(store, ConversationModel())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
        base_url="http://test",
    ) as client:
        assert (await client.get("/v1/capability-markets")).status_code == 422
        assert (
            await client.get("/v1/capability-markets", headers={"X-Roami-Owner": "other"})
        ).status_code == 403
        response = await client.get("/v1/capability-markets", headers={"X-Roami-Owner": "local"})
        assert len(response.json()["data"]["sources"]) == 3
        response = await client.post(
            "/v1/capability-markets/preview",
            headers={"X-Roami-Owner": "local"},
            json={"source": "missing", "id": "x", "version": "1"},
        )
        assert response.status_code == 409


def test_skill_archive_preserves_assets_and_rejects_symlinks():
    import io
    import tarfile

    from roami_agent.server.skill_market_archive import unpack_skill

    def archive(symlink=False):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as bundle:
            for name, raw in {
                "repository/skills/flow/SKILL.md": b"---\nname: workflow\n---\nInstructions",
                "repository/skills/flow/scripts/check.py": b"print('checked')",
                "repository/LICENSE": b"MIT",
            }.items():
                item = tarfile.TarInfo(name)
                item.size = len(raw)
                if symlink and name.endswith("check.py"):
                    item.type = tarfile.SYMTYPE
                    item.linkname = "/etc/passwd"
                    item.size = 0
                    bundle.addfile(item)
                else:
                    bundle.addfile(item, io.BytesIO(raw))
        return output.getvalue()

    text, files = unpack_skill(archive(), "workflow")
    assert "Instructions" in text
    assert base64.b64decode(files["scripts/check.py"]) == b"print('checked')"
    assert base64.b64decode(files["LICENSE"]) == b"MIT"
    with pytest.raises(DomainError, match="INVALID_SKILL_PACKAGE"):
        unpack_skill(archive(symlink=True), "workflow")


async def test_skill_frontmatter_name_can_differ_from_repository_folder(monkeypatch):
    async def fetch(url, **kwargs):
        if url.endswith("/commits/HEAD"):
            return {"sha": "a" * 40}
        return {"tree": [{"path": "skills/react/SKILL.md", "type": "blob"}]}

    async def archived(owner, repo, name, fetch):
        assert (owner, repo, name) == ("publisher", "repository", "publisher-react")
        return (
            "---\nname: publisher-react\n---\nInstructions",
            {"SKILL.md": "SW5zdHJ1Y3Rpb25z"},
            "b" * 40,
        )

    monkeypatch.setattr(market_catalogs, "fetch", fetch)
    monkeypatch.setattr(market_catalogs, "download_archive", archived)
    entry, commit = await market_catalogs.skill_entry("publisher/repository/publisher-react")
    assert entry["name"] == "publisher-react" and commit == "b" * 40
