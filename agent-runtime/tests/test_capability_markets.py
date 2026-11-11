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


@pytest.fixture(autouse=True)
def market_api_credentials(monkeypatch):
    monkeypatch.delenv("VERCEL_OIDC_TOKEN", raising=False)


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

    async def archived(owner, repo, name, fetch, *, commit=""):
        assert commit == "a" * 40
        assert (owner, repo, name) == ("publisher", "repository", "publisher-react")
        return (
            "---\nname: publisher-react\n---\nInstructions",
            {"SKILL.md": "SW5zdHJ1Y3Rpb25z"},
            commit,
        )

    monkeypatch.setattr(market_catalogs, "fetch", fetch)
    monkeypatch.setattr(market_catalogs, "download_archive", archived)
    entry, commit = await market_catalogs.skill_entry("publisher/repository/publisher-react")
    assert entry["name"] == "publisher-react" and commit == "a" * 40


@pytest.mark.parametrize("view", ["all-time", "trending", "hot"])
async def test_public_skills_uses_json_leaderboards_with_complete_pagination(monkeypatch, view):
    monkeypatch.delenv("VERCEL_OIDC_TOKEN", raising=False)
    skills = [{"source": "owner/repo", "skillId": "workflow", "name": "workflow", "installs": 1200}]

    async def fetch(url, **kwargs):
        assert url == "https://skills.sh/api/skills/" + view + "/2"
        return {"skills": skills, "hasMore": True}

    monkeypatch.setattr(market_catalogs, "fetch", fetch)
    result = await market_catalogs.search(market_catalogs.DEFAULT_SOURCES[0], "", "2", view)
    assert result["items"][0]["id"] == "owner/repo/workflow"
    assert result["items"][0]["installs"] == 1200
    assert result["nextCursor"] == "3"


async def test_blank_query_only_browses_skill_markets(store, monkeypatch):
    markets = Runtime(store, ConversationModel()).capability_markets

    async def search(*args):
        return {"items": [], "nextCursor": ""}

    monkeypatch.setattr(market_catalogs, "search", search)
    assert await markets.search("local", "skills-sh", "") == {"items": [], "nextCursor": ""}
    with pytest.raises(DomainError, match="INVALID_MARKET_QUERY"):
        await markets.search("local", "npm", "")


async def test_install_skill_to_agents_retains_assets_is_repeatable_and_never_overwrites(
    store, tmp_path, monkeypatch
):
    from roami_agent.server import skill_agent_installation

    roots = {key: tmp_path / key / "skills" for key in ("local", "claude", "opencode")}
    monkeypatch.setattr(skill_agent_installation, "skill_directories", lambda: roots)
    runtime = Runtime(store, ConversationModel())
    entry = {
        "name": "market-workflow",
        "text": "# Instructions",
        "files": {"scripts/check.py": base64.b64encode(b"print('ok')").decode()},
        "origin": {
            "source": "skills-sh",
            "id": "owner/repo/workflow",
            "version": "a" * 40,
            "url": "https://github.com/owner/repo",
        },
    }
    targets = ["local", "claude", "opencode", "roami"]
    result = await skill_agent_installation.install_skill(runtime, "local", entry, targets)
    assert result["targets"] == targets
    for root in roots.values():
        assert (root / entry["name"] / "SKILL.md").read_text() == entry["text"]
        assert (root / entry["name"] / "scripts/check.py").read_bytes() == b"print('ok')"
    assert entry["name"] in runtime.tools.skills
    assert await skill_agent_installation.install_skill(runtime, "local", entry, targets) == result
    # A changed revision must not silently replace any previous installation.
    with pytest.raises(DomainError, match="SKILL_TARGET_EXISTS"):
        await skill_agent_installation.install_skill(
            runtime, "local", {**entry, "text": "Changed"}, ["local"]
        )
    assert (roots["local"] / entry["name"] / "SKILL.md").read_text() == entry["text"]


async def test_agent_install_failure_rolls_back_only_new_links(store, tmp_path, monkeypatch):
    from roami_agent.server import skill_agent_installation

    roots = {key: tmp_path / key for key in ("local", "claude", "opencode")}
    monkeypatch.setattr(skill_agent_installation, "skill_directories", lambda: roots)
    runtime = Runtime(store, ConversationModel())
    entry = {
        "name": "market-workflow",
        "text": "Instructions",
        "origin": {
            "source": "skills-sh",
            "id": "owner/repo/workflow",
            "version": "a" * 40,
            "url": "https://github.com/owner/repo",
        },
    }
    await skill_agent_installation.install_skill(runtime, "local", entry, ["local"])

    async def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(runtime.capability_imports, "save", fail)
    with pytest.raises(DomainError, match="SKILL_INSTALL_FAILED"):
        await skill_agent_installation.install_skill(
            runtime, "local", entry, ["local", "claude", "roami"]
        )
    assert (roots["local"] / entry["name"]).is_symlink()
    assert not (roots["claude"] / entry["name"]).is_symlink()


@pytest.mark.parametrize("targets", [[], ["../escape"], ["local", "local"], "all", [None]])
async def test_agent_install_rejects_invalid_targets_before_writing(store, targets):
    from roami_agent.server.skill_agent_installation import install_skill

    runtime = Runtime(store, ConversationModel())
    with pytest.raises(DomainError, match="INVALID_SKILL_TARGET"):
        await install_skill(runtime, "local", {"name": "workflow"}, targets)


async def test_http_prepared_skill_installs_to_selected_local_agents(store, tmp_path, monkeypatch):
    from roami_agent.server import skill_agent_installation

    roots = {key: tmp_path / key for key in ("local", "claude", "opencode")}
    monkeypatch.setattr(skill_agent_installation, "skill_directories", lambda: roots)
    entry = {
        "name": "market-flow",
        "text": "---\nname: market-flow\ndescription: Workflow\n---\nInstructions",
        "origin": {
            "source": "skills-sh",
            "id": "owner/repo/market-flow",
            "version": "a" * 40,
            "url": "https://github.com/owner/repo",
        },
    }

    async def preview(*args):
        return {"kind": "skills", "options": [{"label": "market-flow", "entry": entry}]}

    monkeypatch.setattr(market_catalogs, "preview", preview)
    runtime = Runtime(store, ConversationModel())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
        base_url="http://test",
        headers={"X-Roami-Owner": "local"},
    ) as client:
        prepared = await client.post(
            "/v1/capability-markets/prepare",
            json={"source": "skills-sh", "id": "owner/repo/market-flow", "version": ""},
        )
        assert prepared.status_code == 200
        payload = {
            "previewId": prepared.json()["data"]["previewId"],
            "option": 0,
            "targets": ["local", "claude", "opencode", "roami"],
        }
        response = await client.post("/v1/capability-markets/install", json=payload)
        assert response.status_code == 200
        assert response.json()["data"]["targets"] == payload["targets"]
        assert entry["name"] in runtime.tools.skills
        for root in roots.values():
            assert (root / entry["name"] / "SKILL.md").read_text() == entry["text"]
        assert (
            await client.post("/v1/capability-markets/install", json=payload)
        ).json() == response.json()
        expired = await client.post(
            "/v1/capability-markets/install", json={**payload, "previewId": "expired"}
        )
        assert expired.status_code == 409


@pytest.mark.parametrize("stage", ["tree", "file"])
async def test_skill_preview_falls_back_after_later_github_failures_without_changing_commit(
    monkeypatch, stage
):
    commit = "a" * 40

    async def fetch(url, **kwargs):
        if url.endswith("/commits/HEAD"):
            return {"sha": commit}
        if "/git/trees/" in url:
            if stage == "tree":
                raise DomainError("MARKET_RATE_LIMITED", 429)
            return {
                "tree": [
                    {
                        "path": "skills/workflow/SKILL.md",
                        "type": "blob",
                        "mode": "100644",
                        "size": 20,
                    }
                ]
            }
        raise DomainError("MARKET_UNAVAILABLE", 502)

    async def archive(owner, repo, skill, fetch, **kwargs):
        assert kwargs == {"commit": commit}
        return "# Instructions", {}, commit

    monkeypatch.setattr(market_catalogs, "fetch", fetch)
    monkeypatch.setattr(market_catalogs, "download_archive", archive)
    entry, version = await market_catalogs.skill_entry("owner/repo/workflow")
    assert entry["text"] == "# Instructions" and version == commit


async def test_authorized_skills_api_handles_rankings_and_preserves_snapshot(store, monkeypatch):
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "test-oidc-value")
    seen = []
    text = "---\nname: workflow\n---\nInstructions"

    async def fetch(url, **kwargs):
        assert kwargs["headers"] == {"Authorization": "Bearer test-oidc-value"}
        seen.append((url, kwargs))
        if url.endswith("/api/v1/skills"):
            assert kwargs["params"] == {"view": "hot", "page": 0, "per_page": 20}
            return {
                "data": [
                    {
                        "id": "owner/repo/workflow",
                        "name": "workflow",
                        "source": "owner/repo",
                        "installs": 10,
                    }
                ],
                "pagination": {"hasMore": True},
            }
        assert url.endswith("/api/v1/skills/owner/repo/workflow")
        return {
            "id": "owner/repo/workflow",
            "files": [
                {"path": "SKILL.md", "contents": text},
                {"path": "scripts/check.py", "contents": "print('ok')"},
            ],
        }

    monkeypatch.setattr(market_catalogs, "fetch", fetch)
    runtime = Runtime(store, ConversationModel())
    markets = runtime.capability_markets
    result = await markets.search("local", "skills-sh", "", view="hot")
    assert result["nextCursor"] == "1"
    preview = await markets.preview(
        "local", {"source": "skills-sh", "id": "owner/repo/workflow", "version": ""}
    )
    entry = preview["options"][0]["entry"]
    assert entry["text"] == text
    assert base64.b64decode(entry["files"]["scripts/check.py"]) == b"print('ok')"
    assert entry["origin"]["version"].startswith("sha256:")
    assert entry["origin"]["url"] == "https://skills.sh/owner/repo/workflow"
    assert len(seen) == 2


async def test_vercel_authorization_is_never_sent_to_a_custom_mirror(monkeypatch):
    monkeypatch.setenv("VERCEL_OIDC_TOKEN", "test-oidc-value")

    async def fetch(url, **kwargs):
        assert url == "https://mirror.example.test/api/skills/all-time/0"
        assert "headers" not in kwargs
        return {"skills": [], "hasMore": False}

    source = {**market_catalogs.DEFAULT_SOURCES[0], "url": "https://mirror.example.test"}
    monkeypatch.setattr(market_catalogs, "fetch", fetch)
    assert await market_catalogs.search(source, "") == {"items": [], "nextCursor": ""}


async def test_browser_preview_returns_full_content_and_receipt_in_one_response(store, monkeypatch):
    monkeypatch.delenv("VERCEL_OIDC_TOKEN", raising=False)
    entry = {
        "name": "workflow",
        "text": "Instructions" * 1000,
        "files": {"scripts/check.py": "cHJpbnQoMSk="},
        "origin": {
            "source": "skills-sh",
            "id": "owner/repo/workflow",
            "version": "a" * 40,
            "url": "https://github.com/owner/repo",
        },
    }

    async def preview(*args):
        return {"kind": "skills", "options": [{"label": "workflow", "entry": entry}]}

    monkeypatch.setattr(market_catalogs, "preview", preview)
    runtime = Runtime(store, ConversationModel())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
        base_url="http://test",
        headers={"X-Roami-Owner": "local"},
    ) as client:
        response = await client.post(
            "/v1/capability-markets/preview",
            json={"source": "skills-sh", "id": "owner/repo/workflow", "version": ""},
        )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["options"][0]["entry"] == entry
    assert data["previewId"] in runtime.capability_markets.installations.receipts


async def test_raw_github_blocked_uses_the_exact_tree_blob_instead(monkeypatch):
    commit, blob_sha = "a" * 40, "b" * 40
    instructions = b"---\nname: workflow\n---\nInstructions"
    seen = []

    async def fetch(url, **kwargs):
        seen.append(url)
        if url.endswith("/commits/HEAD"):
            return {"sha": commit}
        if "/git/trees/" in url:
            return {
                "tree": [
                    {
                        "path": "skills/workflow/SKILL.md",
                        "sha": blob_sha,
                        "type": "blob",
                        "mode": "100644",
                        "size": len(instructions),
                    }
                ]
            }
        if "raw.githubusercontent.com" in url:
            raise DomainError("MARKET_UNAVAILABLE", 502)
        assert url.endswith("/git/blobs/" + blob_sha)
        return {
            "sha": blob_sha,
            "encoding": "base64",
            "content": base64.b64encode(instructions).decode() + "\n",
        }

    monkeypatch.setattr(market_catalogs, "fetch", fetch)
    entry, version = await market_catalogs.skill_entry("owner/repo/workflow")
    assert entry["text"] == instructions.decode() and version == commit
    assert len(seen) == 4


async def test_upstream_api_authorization_error_does_not_log_out_roami(monkeypatch):
    client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda _: httpx.Response(401, json={"error": "authentication_required"})
    )
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: client(**kwargs, transport=transport)
    )
    with pytest.raises(DomainError, match="MARKET_AUTH_REQUIRED") as caught:
        await market_catalogs.fetch("https://skills.sh/api/v1/skills")
    assert caught.value.status == 503
