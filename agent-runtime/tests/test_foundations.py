import json
from pathlib import Path

import httpx
import pytest
from test_runtime import ConversationModel, until

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.server.http import create_app
from roami_agent.storage.database import row
from roami_agent.tools.foundations import FOUNDATIONS


def call(name, args):
    return {"id": "fixture", "function": {"name": name, "arguments": json.dumps(args)}}


def cli(name, args):
    return call(
        "bash",
        {"argv": ["roami", "agent", "capability", "call", name, "--input", json.dumps(args)]},
    )


async def test_actual_catalog_and_settings_have_only_seven_tools(store):
    runtime = Runtime(store, ConversationModel())
    assert {x["function"]["name"] for x in runtime.tools.catalog()} == set(FOUNDATIONS)
    assert {x["function"]["name"] for x in runtime.tools.catalog("worker")} == {
        "read",
        "bash",
        "edit",
        "write",
        "tool_search",
    }
    assert {x["function"]["name"] for x in runtime.tools.catalog("research")} == {
        "read",
        "bash",
        "tool_search",
    }
    view = runtime.capability_settings.view("local")
    assert {x["name"] for x in view["tools"]} == set(FOUNDATIONS)
    operations = {x["name"] for group in view["cli"] for x in group["commands"]}
    assert "session_send" in operations and "web_research" not in operations


async def test_search_skill_loading_and_disable_policy(store):
    runtime = Runtime(store, ConversationModel())
    result = await runtime.tools.invoke(
        call("tool_search", {"query": "roami-dispatch"}), "main", {}
    )
    skill = next(x for x in result["items"] if x["kind"] == "skill")
    assert skill["location"] == "skill://roami-dispatch"
    assert (
        "capability"
        in (await runtime.tools.invoke(call("read", {"path": skill["location"]}), "main", {}))[
            "text"
        ]
    )
    assert any(
        x["name"] == "session_send"
        for x in runtime.tools.directory.search("发消息", "cli", 10)["items"]
    )
    before = runtime.tools.directory.search("session_send", "cli", 10)
    await runtime.capability_settings.save(
        "local", {"kind": "tools", "name": "session_send", "enabled": False}
    )
    after = runtime.tools.directory.search("session_send", "cli", 10)
    assert before["catalogVersion"] != after["catalogVersion"]
    assert not any(x["name"] == "session_send" for x in after["items"])
    with pytest.raises(DomainError, match="TOOL_DISABLED"):
        await runtime.tools.invoke(
            cli("session_send", {"sessionId": "never", "text": "never"}), "main", {}
        )
    await runtime.capability_settings.save(
        "local", {"kind": "skills", "name": "roami-dispatch", "enabled": False}
    )
    with pytest.raises(DomainError, match="SKILL_DISABLED"):
        await runtime.tools.invoke(call("read", {"path": skill["location"]}), "main", {})


async def test_main_foundations_preserve_file_hashes(store, tmp_path):
    runtime = Runtime(store, ConversationModel(), settings=Settings(shell_roots=(tmp_path,)))
    path = str(tmp_path / "example.txt")
    await runtime.tools.invoke(
        call("write", {"path": path, "expectedSha256": None, "content": "first"}), "main", {}
    )
    original = await runtime.tools.invoke(call("read", {"path": path}), "main", {})
    await runtime.tools.invoke(
        call(
            "edit",
            {
                "path": path,
                "expectedSha256": original["sha256"],
                "oldText": "first",
                "newText": "second",
            },
        ),
        "main",
        {},
    )
    assert Path(path).read_text() == "second"
    with pytest.raises(DomainError):
        await runtime.tools.invoke(
            call(
                "edit",
                {
                    "path": path,
                    "expectedSha256": original["sha256"],
                    "oldText": "second",
                    "newText": "wrong",
                },
            ),
            "main",
            {},
        )
    await runtime.files.close()


async def test_bash_cli_records_actual_read_effect_and_timeline(store):
    class Model:
        model = "foundation-fixture"

        async def stream(self, messages, tools):
            yield (
                ModelEvent("text", "Done")
                if messages[-1]["role"] == "tool"
                else ModelEvent("tool", cli("memory_search", {"query": "fixture"}))
            )

    runtime = Runtime(store, Model())
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "one", "Read history")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
        )
        tool = await store.call(
            lambda db: row(db, "SELECT * FROM tool_calls WHERE turn_id=?", (receipt["turnId"],))
        )
        assert (tool["tool_name"], tool["effect"], tool["state"]) == (
            "memory_search",
            "read",
            "succeeded",
        )
        view = await runtime.conversations.messages("alice", c["id"])
        assert any(x["name"] == "memory_search" for x in view["activities"])
    finally:
        await runtime.close()


async def test_research_and_main_cannot_escape_cli_admission(store):
    runtime = Runtime(store, ConversationModel())
    for wire in [
        call("bash", {"command": "pwd"}),
        call("read", {"path": "/etc/passwd"}),
        cli("session_send", {"sessionId": "x", "text": "x"}),
    ]:
        with pytest.raises(DomainError, match="TOOL_UNAVAILABLE"):
            await runtime.tools.invoke(wire, "research", {})
    with pytest.raises(DomainError, match="USE_REGISTERED_CLI_CAPABILITY"):
        await runtime.tools.invoke(
            call("bash", {"argv": ["roami", "session", "kill-session"]}), "main", {}
        )


async def test_cli_directory_and_unbound_call_rejection(store):
    runtime = Runtime(store, ConversationModel())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "local"},
    ) as client:
        response = await client.get("/v1/tool-directory", params={"query": "roami-dispatch"})
        assert response.status_code == 200 and response.json()["data"]["items"]
        assert (await client.get("/v1/tool-directory/session_send")).status_code == 200
        response = await client.post(
            "/v1/tool-directory/session_send/call",
            json={
                "turnId": "missing",
                "toolCallId": "missing",
                "arguments": {"sessionId": "x", "text": "x"},
            },
        )
        assert response.status_code == 409
        assert not await store.call(lambda db: row(db, "SELECT id FROM tool_calls"))
