"""Managed registrations survive restarts and use existing execution boundaries."""

import json
import os
import sys
from pathlib import Path

import httpx
import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.server.http import create_app


async def invoke(runtime, name, args, binding=None):
    return await runtime.tools.invoke(
        {"function": {"name": name, "arguments": json.dumps(args)}}, "worker", binding or {}
    )


async def test_skill_creation_edit_policy_removal_and_restart(store):
    runtime = Runtime(store, ConversationModel())
    imports = runtime.capability_imports
    skill = {"name": "workflow", "text": "# Original instructions", "description": "Test workflow"}
    await imports.save("local", "skills", skill)
    assert (await invoke(runtime, "read", {"path": "skill://workflow"}))["text"] == skill["text"]
    assert os.stat(imports.path).st_mode & 0o777 == 0o600
    assert os.stat(imports.path.parent).st_mode & 0o777 == 0o700
    with pytest.raises(DomainError, match="CAPABILITY_ALREADY_EXISTS"):
        await imports.save("local", "skills", skill)
    await imports.save("local", "skills", {**skill, "text": "# Updated"}, "workflow")
    recreated = Runtime(store, ConversationModel())
    assert (await invoke(recreated, "read", {"path": "skill://workflow"}))["text"] == "# Updated"
    await recreated.capability_settings.save(
        "local", {"kind": "skills", "name": "workflow", "enabled": False}
    )
    with pytest.raises(DomainError, match="SKILL_DISABLED"):
        await invoke(recreated, "read", {"path": "skill://workflow"})
    await recreated.capability_imports.save("local", "skills", None, "workflow", remove=True)
    assert "workflow" not in Runtime(store, ConversationModel()).tools.skills
    with pytest.raises(DomainError, match="MANAGED_CAPABILITY_NOT_FOUND"):
        await imports.save("local", "skills", None, "roami", remove=True)


async def test_cli_executes_argv_without_shell_and_respects_roots(store, tmp_path):
    runtime = Runtime(store, ConversationModel(), settings=Settings(shell_roots=(tmp_path,)))
    command = {
        "name": "echo",
        "description": "Print JSON",
        "argv": [sys.executable, "-c", "import sys; print(sys.argv[1])", "{input}"],
        "cwd": str(tmp_path),
    }
    await runtime.capability_imports.save("local", "cli", command)
    payload = {"text": "$(touch /tmp/should-never-exist); `echo injected`"}
    result = await invoke(
        runtime,
        "bash",
        {
            "argv": [
                "roami",
                "agent",
                "capability",
                "call",
                "cli_echo",
                "--input",
                json.dumps(payload),
            ]
        },
    )
    assert json.loads(result["stdout"]) == payload
    await runtime.capability_settings.save(
        "local", {"kind": "tools", "name": "cli_echo", "enabled": False}
    )
    with pytest.raises(DomainError, match="TOOL_DISABLED"):
        await invoke(runtime, "cli_echo", payload)
    await runtime.capability_settings.save(
        "local", {"kind": "tools", "name": "cli_echo", "enabled": True}
    )
    await runtime.capability_imports.save(
        "local", "cli", {**command, "cwd": str(tmp_path.parent)}, "echo"
    )
    with pytest.raises(DomainError, match="WORKSPACE_OUTSIDE_CONFIGURED_ROOTS"):
        await invoke(runtime, "cli_echo", payload)
    recreated = Runtime(store, ConversationModel(), settings=Settings(shell_roots=(tmp_path,)))
    assert "cli_echo" in recreated.tools.registry
    await recreated.capability_imports.save("local", "cli", None, "echo", remove=True)
    assert "cli_echo" not in recreated.tools.registry


async def test_mcp_batch_is_atomic_lazy_and_supports_real_discovery(store, tmp_path):
    runtime = Runtime(store, ConversationModel())
    imports = runtime.capability_imports
    (tmp_path / "state.json").write_text("{}")
    config = {
        "command": sys.executable,
        "args": [str(Path(__file__).with_name("mcp_fixture.py")), str(tmp_path)],
    }
    with pytest.raises(DomainError, match="INVALID_MCP_CONFIG"):
        await imports.save(
            "local",
            "mcp",
            {"mcpServers": {"fixture": config, "bad": {"url": "http://remote.invalid/mcp"}}},
        )
    assert not imports.path.exists()
    assert not runtime.mcp.connections
    await imports.save("local", "mcp", {"mcpServers": {"fixture": config}})
    assert runtime.mcp.connections["fixture"].task is None
    assert runtime.capability_settings.view("local")["mcp"][0]["state"] == "not_connected"
    try:
        result = await runtime.mcp.discover({"server": "fixture"}, {})
        assert result["tools"]
        assert runtime.capability_settings.view("local")["mcp"][0]["state"] == "connected"
        runtime.mcp.connections["fixture"].current = object()
        with pytest.raises(DomainError, match="CAPABILITY_BUSY"):
            await imports.save("local", "mcp", None, "fixture", remove=True)
        runtime.mcp.connections["fixture"].current = None
        await imports.save("local", "mcp", None, "fixture", remove=True)
        assert not runtime.mcp.connections
        assert "mcp_discover" not in runtime.tools.registry
        assert not any(name.startswith("mcp_fixture_") for name in runtime.tools.registry)
    finally:
        await runtime.mcp.close()


async def test_failed_persistence_leaves_runtime_untouched(store, monkeypatch):
    runtime = Runtime(store, ConversationModel())
    imports = runtime.capability_imports
    original = {"name": "workflow", "text": "Original"}
    await imports.save("local", "skills", original)
    before = imports.path.read_bytes()

    def fail(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        await imports.save("local", "skills", {**original, "text": "Replacement"}, "workflow")
    assert imports.path.read_bytes() == before
    assert runtime.tools.skills["workflow"]["text"] == "Original"


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("skills", {"name": "../escape", "text": "bad"}),
        ("skills", {"name": "valid", "text": ""}),
        ("cli", {"name": "valid", "argv": "echo"}),
        (
            "cli",
            {
                "name": "valid",
                "argv": ["echo"],
                "schema": {"type": "object", "$ref": "https://example.com/schema"},
            },
        ),
        (
            "mcp",
            {"name": "valid", "config": {"command": "echo", "env": {"TOKEN": "fixture"}}},
        ),
        ("mcp", {"name": "valid", "config": {"transport": "streamable_http", "url": None}}),
    ],
)
async def test_invalid_input_has_no_side_effects(store, kind, payload):
    runtime = Runtime(store, ConversationModel())
    with pytest.raises(DomainError):
        await runtime.capability_imports.save("local", kind, payload)
    assert not runtime.capability_imports.path.exists()


async def test_http_limits_ownership_and_managed_crud(store):
    runtime = Runtime(store, ConversationModel())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "local"},
    ) as client:
        path = "/v1/capability-imports/skills"
        assert (await client.post(path, content=b"x" * 65537)).status_code == 413
        payload = {"name": "workflow", "text": "Original"}
        assert (
            await client.post(path, json=payload, headers={"X-Roami-Owner": "foreign"})
        ).status_code == 403
        assert not runtime.capability_imports.path.exists()
        assert (await client.post(path, json=payload)).status_code == 200
        assert (await client.post(path, json=payload)).status_code == 409
        assert (
            await client.put(path + "/workflow", json={**payload, "text": "Changed"})
        ).status_code == 200
        assert (await client.delete(path + "/workflow")).status_code == 200
        assert (await client.delete(path + "/roami")).status_code == 404


async def test_mcp_limit_edit_and_restart_preserve_all_connections(store):
    runtime = Runtime(store, ConversationModel())
    servers = {f"server{index}": {"command": "fixture-server"} for index in range(16)}
    await runtime.capability_imports.save("local", "mcp", {"mcpServers": servers})
    with pytest.raises(DomainError, match="INVALID_MCP_CONFIG"):
        await runtime.capability_imports.save(
            "local", "mcp", {"name": "extra", "config": {"command": "fixture-server"}}
        )
    await runtime.capability_imports.save(
        "local", "mcp", {"name": "server0", "config": {"command": "updated-server"}}, "server0"
    )
    recreated = Runtime(store, ConversationModel())
    assert len(recreated.mcp.connections) == 16
    assert recreated.mcp.connections["server0"].config["command"] == "updated-server"
    assert all(connection.task is None for connection in recreated.mcp.connections.values())


async def test_unicode_skill_uses_utf8_size_and_rejects_nonprivate_storage(store):
    runtime = Runtime(store, ConversationModel())
    value = {"name": "workflow", "text": "流程" * 9000}
    await runtime.capability_imports.save("local", "skills", value)
    assert Runtime(store, ConversationModel()).tools.skills["workflow"]["text"] == value["text"]
    runtime.capability_imports.path.chmod(0o644)
    with pytest.raises(DomainError, match="CAPABILITY_IMPORT_PRIVATE_FILE_REQUIRED"):
        Runtime(store, ConversationModel())


async def test_external_skill_names_can_be_longer_than_mcp_names(store):
    runtime = Runtime(store, ConversationModel())
    name = "external-workflow-instructions"
    await runtime.capability_imports.save("local", "skills", {"name": name, "text": "Instructions"})
    assert name in runtime.tools.skills
    with pytest.raises(DomainError, match="INVALID_CAPABILITY_NAME"):
        await runtime.capability_imports.save(
            "local", "mcp", {"name": name, "config": {"command": "fixture"}}
        )
