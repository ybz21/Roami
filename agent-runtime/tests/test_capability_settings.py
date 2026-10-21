"""Disabling a capability blocks stale invocations as well as new model catalogs."""

import json
import os

import httpx
import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.server.http import create_app


def external_settings():
    return Settings(
        http_tools={
            "fixture": {
                "url": "https://example.invalid",
                "description": "External read-only fixture",
            }
        }
    )


async def test_external_tool_policy_blocks_stale_calls_and_survives_recreation(store):
    runtime = Runtime(store, ConversationModel(), settings=external_settings())
    settings = runtime.capability_settings
    await settings.save("local", {"kind": "tools", "name": "http_fixture", "enabled": False})
    with pytest.raises(DomainError, match="TOOL_DISABLED"):
        await runtime.tools.invoke(
            {"function": {"name": "http_fixture", "arguments": "{}"}}, "worker", {}
        )
    recreated = Runtime(store, ConversationModel(), settings=external_settings())
    assert "http_fixture" in recreated.tools.disabled_tools
    assert os.stat(settings.path).st_mode & 0o777 == 0o600
    await recreated.capability_settings.save(
        "local", {"kind": "tools", "name": "http_fixture", "enabled": True}
    )
    assert any(
        item["name"] == "http_fixture"
        for item in recreated.tools.directory.list("http_fixture", "tool", 10, "worker")["items"]
    )


async def test_external_skill_can_be_disabled_and_reenabled(store, tmp_path):
    root = tmp_path / "configured-skills"
    path = root / "external-workflow" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\nname: external-workflow\ndescription: External workflow\n---\nExternal content"
    )
    runtime = Runtime(store, ConversationModel(), settings=Settings(skill_roots=(root,)))
    await runtime.capability_settings.save(
        "local", {"kind": "skills", "name": "external-workflow", "enabled": False}
    )
    call = {"function": {"name": "read", "arguments": '{"path":"skill://external-workflow"}'}}
    with pytest.raises(DomainError, match="SKILL_DISABLED"):
        await runtime.tools.invoke(call, "main", {})
    await runtime.capability_settings.save(
        "local", {"kind": "skills", "name": "external-workflow", "enabled": True}
    )
    assert (await runtime.tools.invoke(call, "main", {}))["version"]


async def test_builtins_reject_both_enable_and_disable_and_old_disabled_config_is_ignored(store):
    runtime = Runtime(store, ConversationModel(), settings=external_settings())
    for kind, name in [
        ("tools", tool["name"])
        for tool in runtime.capability_settings.view("local")["tools"]
        if tool["source"] == "builtin"
    ] + [("tools", "session_send"), ("skills", "roami"), ("skills", "browser_use")]:
        for enabled in (True, False):
            with pytest.raises(DomainError, match="BUILTIN_CAPABILITY_READ_ONLY"):
                await runtime.capability_settings.save(
                    "local", {"kind": kind, "name": name, "enabled": enabled}
                )
    path = runtime.capability_settings.path
    path.parent.mkdir(parents=True, mode=0o700)
    path.write_text(
        json.dumps({"tools": ["bash", "session_send", "http_fixture"], "skills": ["roami"]})
    )
    path.chmod(0o600)
    recreated = Runtime(store, ConversationModel(), settings=external_settings())
    assert recreated.tools.disabled_tools == {"http_fixture"}
    assert recreated.tools.disabled_skills == set()
    assert all(
        tool["enabled"] and not tool["mutable"]
        for tool in recreated.capability_settings.view("local")["tools"]
        if tool["source"] == "builtin"
    )


async def test_http_catalog_omits_provider_secrets_and_rejects_foreign_owner(store):
    runtime = Runtime(store, ConversationModel())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "local"},
    ) as client:
        response = await client.get("/v1/capability-settings")
        assert response.status_code == 200
        data = response.json()["data"]
        assert any(
            skill["name"] == "roami" and skill["source"] == "builtin" for skill in data["skills"]
        )
        assert {tool["name"] for tool in data["tools"]} == {
            "read",
            "bash",
            "edit",
            "write",
            "tool_list",
            "delegate",
            "ask_user",
            "conversation_history",
            "task_reply",
            "task_queue_reply",
            "reply",
        }
        assert any(
            command["name"] == "roami" for group in data["cli"] for command in group["commands"]
        )
        assert not any(key in data for key in ["apiKey", "headers", "env", "command"])
        assert (
            await client.get("/v1/capability-settings", headers={"X-Roami-Owner": "alice"})
        ).status_code == 403
        assert (
            await client.put(
                "/v1/capability-settings",
                json={"kind": "tools", "name": "invented", "enabled": False},
            )
        ).status_code == 404
        assert (
            await client.put(
                "/v1/capability-settings",
                json={"kind": [], "name": "session_send", "enabled": False},
            )
        ).status_code == 400
        assert not runtime.capability_settings.path.exists()


async def test_failed_persistence_does_not_change_runtime_policy(store, monkeypatch):
    runtime = Runtime(store, ConversationModel(), settings=external_settings())

    def reject(*args):
        raise OSError("write rejected")

    monkeypatch.setattr(os, "replace", reject)
    with pytest.raises(OSError):
        await runtime.capability_settings.save(
            "local", {"kind": "tools", "name": "http_fixture", "enabled": False}
        )
    assert "http_fixture" not in runtime.tools.disabled_tools
    assert not runtime.capability_settings.path.exists()


async def test_import_contract_accepts_only_valid_authenticated_payloads(store):
    runtime = Runtime(store, ConversationModel())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "local"},
    ) as client:
        assert (await client.get("/v1/capability-imports")).json()["data"]["available"] is True
        for kind in ["skills", "cli", "mcp"]:
            assert (
                await client.post("/v1/capability-imports/" + kind, content=b"untrusted bytes")
            ).status_code == 400
        assert (
            await client.post("/v1/capability-imports/skills", headers={"X-Roami-Owner": "other"})
        ).status_code == 403
        assert not runtime.capability_imports.path.exists()
