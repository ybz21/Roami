"""Requested MCP lookups use regular Native workers, preserving browser isolation."""

import json

import pytest
from test_foundations import call, cli
from test_runtime import ConversationModel, until
from test_web_research import MemoryModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row

NAME = "mcp_fixture_search"
REQUEST = "Use the configured MCP to search for the public documentation."


async def test_mcp_lookup_worker_discovers_and_calls_the_tool_without_a_workspace(store):
    invoked = []

    class Main:
        model = "mcp-routing-main"

        async def stream(self, messages, tools):
            if messages[-1]["content"] == REQUEST:
                yield ModelEvent(
                    "tool",
                    call(
                        "delegate",
                        {
                            "goal": REQUEST,
                            "requestComplete": True,
                            "executor": "native",
                            "target": {"kind": "new_session"},
                        },
                    ),
                )
            else:
                yield ModelEvent("text", "The documentation lookup is scheduled.")

    class Worker:
        model = "mcp-routing-worker"
        step = 0

        async def stream(self, messages, tools):
            self.step += 1
            if self.step == 1:
                discovery = call("tool_list", {"query": "fixture", "kind": "mcp"})
                discovery["id"] = "discover-mcp"
                yield ModelEvent("tool", discovery)
            elif self.step == 2:
                catalog = json.loads(messages[-1]["content"])
                assert [item["name"] for item in catalog["items"]] == [NAME]
                search = cli(NAME, {"query": "public documentation"})
                search["id"] = "search-mcp"
                yield ModelEvent("tool", search)
            else:
                assert "Fixture documentation" in messages[-1]["content"]
                yield ModelEvent("text", "Fixture documentation: https://example.org/docs")

    async def search(args, binding):
        assert binding["role"] == "worker"
        assert not binding.get("workspace")
        invoked.append(args["query"])
        return {
            "content": [{"type": "text", "text": "Fixture documentation: https://example.org/docs"}]
        }

    def unexpected_workspace(*args, **kwargs):
        pytest.fail("An MCP lookup must not prepare a coding workspace")

    runtime = Runtime(
        store,
        Main(),
        worker_model=Worker(),
        memory_model=MemoryModel(),
        settings=Settings(workers=1),
    )
    runtime.tools.add(
        Tool(
            NAME,
            "Fixture documentation search",
            object_schema({"query": {"type": "string"}}, ["query"]),
            search,
            effect="read",
            source="external",
            main=True,
        )
    )
    runtime.dispatch.native_executor.workspace_factory = unexpected_workspace
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        await runtime.chat.submit("alice", conversation["id"], "mcp-lookup", REQUEST)
        await until(
            store, lambda db: row(db, "SELECT id FROM tasks WHERE state IN ('succeeded','failed')")
        )
        task = await store.call(
            lambda db: row(db, "SELECT state,intent_json,target_json FROM tasks")
        )
        assert task["state"] == "succeeded"
        assert json.loads(task["intent_json"])["target"] == {"kind": "new_session"}
        assert invoked == ["public documentation"]
        assert (
            await store.call(
                lambda db: db.execute(
                    "SELECT count(*) FROM tool_calls WHERE tool_name=? AND state='succeeded'",
                    (NAME,),
                ).fetchone()[0]
            )
            == 1
        )
    finally:
        await runtime.close()


@pytest.mark.parametrize("restricted", ["research", "disabled"])
async def test_mcp_lookup_keeps_browser_and_disabled_tool_boundaries(store, restricted):
    runtime = Runtime(store, ConversationModel())

    async def search(args, binding):
        pytest.fail("A filtered MCP must not execute")

    runtime.tools.add(
        Tool(
            NAME,
            "Fixture search",
            object_schema({}),
            search,
            effect="read",
            source="external",
            main=True,
        )
    )
    role = "research" if restricted == "research" else "worker"
    if restricted == "disabled":
        runtime.tools.disabled_tools.add(NAME)
    try:
        catalog = runtime.tools.directory.list("fixture", "mcp", role=role)
        assert catalog["items"] == []
        if role == "research":
            assert "browser-only" in catalog["hint"]
            assert "do not report the server unavailable" in catalog["hint"]
        with pytest.raises(DomainError, match="TOOL_UNAVAILABLE|TOOL_DISABLED"):
            await runtime.tools.invoke(cli(NAME, {}), role, {"owner": "alice"})
    finally:
        await runtime.close()
