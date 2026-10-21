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
        "tool_list",
    }
    assert {x["function"]["name"] for x in runtime.tools.catalog("research")} == {
        "read",
        "bash",
        "tool_list",
    }
    view = runtime.capability_settings.view("local")
    assert {x["name"] for x in view["tools"]} == set(FOUNDATIONS)
    operations = {x["name"] for group in view["cli"] for x in group["commands"]}
    assert operations == {"roami"}


async def test_search_skill_loading_and_disable_policy(store):
    runtime = Runtime(store, ConversationModel())
    result = await runtime.tools.invoke(call("tool_list", {"query": "roami"}), "main", {})
    skill = next(x for x in result["items"] if x["kind"] == "skill")
    assert skill["location"] == "skill://roami"
    assert (
        "roami"
        in (await runtime.tools.invoke(call("read", {"path": skill["location"]}), "main", {}))[
            "text"
        ]
    )
    assert any(
        x["name"] == "roami" for x in runtime.tools.directory.list("发消息", "cli", 10)["items"]
    )
    before = runtime.tools.directory.list("session_send", "cli", 10)
    for kind, name in (("tools", "session_send"), ("skills", "roami")):
        with pytest.raises(DomainError, match="BUILTIN_CAPABILITY_READ_ONLY"):
            await runtime.capability_settings.save(
                "local", {"kind": kind, "name": name, "enabled": False}
            )
    assert before == runtime.tools.directory.list("session_send", "cli", 10)
    assert (await runtime.tools.invoke(call("read", {"path": skill["location"]}), "main", {}))[
        "text"
    ]


@pytest.mark.parametrize("create_hash", [None, "null"])
async def test_main_foundations_preserve_file_hashes(store, tmp_path, create_hash):
    runtime = Runtime(store, ConversationModel(), settings=Settings(shell_roots=(tmp_path,)))
    path = str(tmp_path / "example.txt")
    await runtime.tools.invoke(
        call("write", {"path": path, "expectedSha256": create_hash, "content": "first"}), "main", {}
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
        assert view["activities"] == []
        events = await runtime.conversations.events("alice", view["conversation"]["id"])
        assert any(e["payload"].get("activity", {}).get("name") == "memory_search" for e in events)
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
        response = await client.get("/v1/tool-directory", params={"query": "roami"})
        assert response.status_code == 200 and response.json()["data"]["items"]
        assert (await client.get("/v1/tool-directory/roami")).status_code == 200
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


async def test_discovery_handles_retired_names_weather_and_kind_misses_without_overview_noise(
    store,
):
    runtime = Runtime(
        store,
        ConversationModel(),
        settings=Settings(browser={"enabled": True, "endpoint": "http://127.0.0.1:9222"}),
    )
    directory = runtime.tools.directory
    found = directory.list("web_research", "all", 5)
    assert found["items"][0]["name"] == "browser_use"
    assert not any(item["name"] == "capability_overview" for item in found["items"])
    for query in ("browser", "browser_open", "网页"):
        result = directory.list(query, "cli", 5, "research")
        assert result["items"][0]["name"] == "roami chrome"
    assert all(
        item["name"] != "capability_overview" for item in directory.list(kind="cli")["items"]
    )
    assert not directory.list("zxqv493", "cli")["items"]


async def test_tool_list_lists_categories_pages_and_removes_old_entry(store):
    from roami_agent.protocol.tools import Tool, object_schema

    runtime = Runtime(store, ConversationModel())

    async def echo(args, binding):
        return args

    runtime.tools.add(
        Tool("mcp_fixture_echo", "MCP fixture echo", object_schema({}), echo, source="external")
    )
    for index in range(12):
        runtime.tools.add(
            Tool(f"cli_page_{index}", "Page fixture", object_schema({}), echo, source="external")
        )
    assert "tool_search" not in runtime.tools.registry
    with pytest.raises(DomainError, match="TOOL_UNAVAILABLE"):
        await runtime.tools.invoke(call("tool_search", {"query": "browser"}), "main", {})
    listed = await runtime.tools.invoke(call("tool_list", {}), "worker", {})
    assert listed["total"] == sum(listed["totals"].values())
    assert listed["totals"]["mcp"] == 1 and listed["totals"]["skill"] > 0
    assert listed["offset"] == 0 and len(listed["items"]) == 10
    assert listed["nextOffset"] == 10 and listed["truncated"]
    skills = await runtime.tools.invoke(call("tool_list", {"kind": "skill"}), "main", {})
    assert skills["total"] and all(item["kind"] == "skill" for item in skills["items"])
    assert "skill" in skills["totals"] and "mcp" in skills["totals"]
    first = await runtime.tools.invoke(call("tool_list", {"kind": "cli", "limit": 1}), "worker", {})
    second = await runtime.tools.invoke(
        call("tool_list", {"kind": "cli", "limit": 1, "offset": first["nextOffset"]}), "worker", {}
    )
    assert first["truncated"] and first["nextOffset"] == 1
    assert first["items"][0]["id"] != second["items"][0]["id"]
    mcp = await runtime.tools.invoke(call("tool_list", {"kind": "mcp"}), "worker", {})
    assert mcp["items"][0]["name"] == "mcp_fixture_echo" and mcp["items"][0]["kind"] == "mcp"
    assert not (
        await runtime.tools.invoke(
            call("tool_list", {"kind": "cli", "query": "mcp_fixture_echo"}), "worker", {}
        )
    )["items"]
    main_mcp = await runtime.tools.invoke(call("tool_list", {"kind": "mcp"}), "main", {})
    assert not main_mcp["items"]
    assert main_mcp["scope"] == "current_role"
    assert "not web search results" in main_mcp["hint"]
    research_mcp = await runtime.tools.invoke(call("tool_list", {"kind": "mcp"}), "research", {})
    assert [item["name"] for item in research_mcp["items"]] == ["mcp_fixture_echo"]
    await runtime.capability_settings.save(
        "local", {"kind": "tools", "name": "mcp_fixture_echo", "enabled": False}
    )
    assert not (await runtime.tools.invoke(call("tool_list", {"kind": "mcp"}), "worker", {}))[
        "items"
    ]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "local"},
    ) as client:
        listed = await client.get("/v1/tool-directory")
        assert listed.status_code == 200 and listed.json()["data"]["offset"] == 0
        response = await client.get(
            "/v1/tool-directory", params={"kind": "skill", "limit": 1, "offset": 1}
        )
        assert response.status_code == 200 and response.json()["data"]["offset"] == 1
        assert (await client.get("/v1/tool-directory?limit=21")).status_code == 422
        assert (await client.get("/v1/tool-directory?offset=-1")).status_code == 422


async def test_malformed_cli_arguments_have_an_executable_recovery_example(store):
    class Repair:
        model = "cli-recovery"
        calls = 0

        async def stream(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                yield ModelEvent("tool", call("bash", {"argv": ["roami", {}]}))
            elif self.calls == 2:
                failure = json.loads(messages[-1]["content"])
                assert failure["error"] == "INVALID_TOOL_ARGUMENTS"
                arguments, _ = json.JSONDecoder().raw_decode(
                    failure["recovery"].split("Example: ", 1)[1]
                )
                assert all(isinstance(value, str) for value in arguments["argv"])
                wire = call("bash", arguments)
                wire["id"] = "repaired"
                yield ModelEvent("tool", wire)
            else:
                assert json.loads(messages[-1]["content"]) == []
                yield ModelEvent("text", "No existing tasks.")

    model = Repair()
    runtime = Runtime(store, model)
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", conversation["id"], "cli", "Check tasks")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
        )
        view = await runtime.conversations.messages("alice", conversation["id"])
        assert view["messages"][-1]["content"]["text"] == "No existing tasks."
        assert model.calls == 3
        assert await runtime.tasks.list("alice") == []
    finally:
        await runtime.close()


async def test_exact_task_status_filters_before_page_limit_and_preserves_scope(store):
    runtime = Runtime(store, ConversationModel())
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", conversation["id"], "Old task", key="old", record_intent=True
        )
        for number in range(201):
            await runtime.tasks.create(
                "alice",
                conversation["id"],
                f"New task {number}",
                key=f"new-{number}",
                record_intent=True,
            )
        assert (
            await store.call(lambda db: db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])
            == 202
        )
        assert task["id"] not in {
            item["id"] for item in await runtime.tasks.list("alice", conversation["id"])
        }
        binding = {"owner": "alice", "conversation": conversation["id"]}
        status = await runtime.tools.invoke(
            cli("task_status", {"taskId": task["id"]}), "main", binding
        )
        assert [item["id"] for item in status] == [task["id"]]
        other = await runtime.conversations.create("alice")
        foreign = await runtime.conversations.create("bob")
        for owner, cid in [("alice", other["id"]), ("bob", foreign["id"])]:
            assert (
                await runtime.tools.invoke(
                    cli("task_status", {"taskId": task["id"]}),
                    "main",
                    {"owner": owner, "conversation": cid},
                )
                == []
            )
    finally:
        await runtime.close()
