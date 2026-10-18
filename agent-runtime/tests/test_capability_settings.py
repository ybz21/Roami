"""Disabling a capability blocks stale invocations as well as new model catalogs."""

import json
import os

import httpx
import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.server.http import create_app


async def test_tool_policy_blocks_stale_calls_and_survives_recreation(store):
    runtime = Runtime(store, ConversationModel())
    settings = runtime.capability_settings
    await settings.save("local", {"kind": "tools", "name": "session_send", "enabled": False})
    assert "session_send" not in {tool["function"]["name"] for tool in runtime.tools.catalog()}
    with pytest.raises(DomainError, match="TOOL_DISABLED"):
        await runtime.tools.invoke(
            {
                "function": {
                    "name": "session_send",
                    "arguments": json.dumps({"sessionId": "existing", "text": "do not deliver"}),
                }
            },
            "main",
            {},
        )
    with pytest.raises(DomainError, match="TOOL_DISABLED"):
        await runtime.tools.invoke(
            {
                "function": {
                    "name": "delegate",
                    "arguments": json.dumps(
                        {
                            "goal": "Do not send",
                            "target": {"kind": "session", "sessionId": "existing"},
                        }
                    ),
                }
            },
            "main",
            {},
        )
    recreated = Runtime(store, ConversationModel())
    assert "session_send" in recreated.tools.disabled_tools
    assert os.stat(settings.path).st_mode & 0o777 == 0o600
    await recreated.capability_settings.save(
        "local", {"kind": "tools", "name": "session_send", "enabled": True}
    )
    assert "session_send" not in {tool["function"]["name"] for tool in recreated.tools.catalog()}
    assert any(
        item["name"] == "session_send"
        for item in recreated.tools.directory.search("session_send", "cli", 10)["items"]
    )


async def test_disabled_skill_cannot_be_read_through_existing_tool_call(store):
    runtime = Runtime(store, ConversationModel())
    await runtime.capability_settings.save(
        "local", {"kind": "skills", "name": "roami-dispatch", "enabled": False}
    )
    call = {"function": {"name": "skill_read", "arguments": '{"name":"roami-dispatch"}'}}
    with pytest.raises(DomainError, match="SKILL_DISABLED"):
        await runtime.tools.invoke(call, "main", {})
    await runtime.capability_settings.save(
        "local", {"kind": "skills", "name": "roami-dispatch", "enabled": True}
    )
    assert (await runtime.tools.invoke(call, "main", {}))["version"]


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
            skill["name"] == "roami-dispatch" and skill["source"] == "builtin"
            for skill in data["skills"]
        )
        assert {tool["name"] for tool in data["tools"]} == {
            "read",
            "bash",
            "edit",
            "write",
            "tool_search",
            "delegate",
            "ask_user",
        }
        assert any(
            command["name"] == "session_send"
            for group in data["cli"]
            for command in group["commands"]
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
    runtime = Runtime(store, ConversationModel())

    def reject(*args):
        raise OSError("write rejected")

    monkeypatch.setattr(os, "replace", reject)
    with pytest.raises(OSError):
        await runtime.capability_settings.save(
            "local", {"kind": "tools", "name": "session_send", "enabled": False}
        )
    assert "session_send" not in runtime.tools.disabled_tools
    assert not runtime.capability_settings.path.exists()


async def test_reserved_import_contract_cannot_accept_or_execute_uploaded_files(store):
    runtime = Runtime(store, ConversationModel())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "local"},
    ) as client:
        response = await client.get("/v1/capability-imports")
        assert response.json()["data"]["available"] is False
        for kind in ["skills", "tools"]:
            response = await client.post(
                "/v1/capability-imports/" + kind, content=b"untrusted bytes"
            )
            assert response.status_code == 501
            assert response.json()["error"]["code"] == "CAPABILITY_IMPORT_RESERVED"
        assert (
            await client.post("/v1/capability-imports/skills", headers={"X-Roami-Owner": "other"})
        ).status_code == 403
        assert not runtime.capability_settings.path.exists()
