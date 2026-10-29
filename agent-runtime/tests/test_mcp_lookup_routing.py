"""All background profiles discover and invoke enabled extra capabilities."""

import json

import pytest
from native_prompt_messages import dialogue_messages
from test_foundations import call, cli
from test_runtime import ConversationModel, until
from test_web_research import MemoryModel

from roami_agent.app import Runtime
from roami_agent.dispatch.web_evidence import retrieved_sources
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row

NAME = "mcp_fixture_search"


@pytest.mark.parametrize("resource_only", [False, True])
@pytest.mark.parametrize("source_kind", ["mcp", "cli", "http"])
@pytest.mark.parametrize("effect", ["read", "write"])
async def test_mcp_lookup_worker_discovers_and_calls_without_a_coding_workspace(
    store, resource_only, source_kind, effect
):
    invoked = []
    name = source_kind + "_fixture_search"
    kind = {"mcp": "mcp", "cli": "cli", "http": "tool"}[source_kind]
    request = "Use the configured " + source_kind.upper() + " to search public documentation."

    class Main:
        model = "mcp-routing-main"

        async def stream(self, messages, tools):
            if messages[-1]["content"] == request:
                yield ModelEvent(
                    "tool",
                    call(
                        "delegate",
                        {
                            "goal": request,
                            "requestComplete": True,
                            "executor": "native",
                            "target": {
                                "kind": "new_session",
                                **({"resourceOnly": True} if resource_only else {}),
                            },
                        },
                    ),
                )
            else:
                yield ModelEvent("text", "The documentation lookup is scheduled.")

    class Worker:
        model = "mcp-routing-worker"
        step = 0

        async def stream(self, messages, tools):
            messages = dialogue_messages(messages)
            self.step += 1
            if self.step == 1:
                discovery = call("tool_list", {"query": "fixture", "kind": kind})
                discovery["id"] = "discover-mcp"
                yield ModelEvent("tool", discovery)
            elif self.step == 2:
                catalog = json.loads(messages[-1]["content"])
                assert [item["name"] for item in catalog["items"]] == [name]
                search = cli(name, {"query": "public documentation"})
                search["id"] = "search-mcp"
                yield ModelEvent("tool", search)
            else:
                assert "Fixture documentation" in messages[-1]["content"]
                yield ModelEvent("text", "Fixture documentation: https://example.org/docs")

    async def search(args, binding):
        assert binding["role"] == ("research" if resource_only else "worker")
        if resource_only:
            assert not binding.get("workspace")
        else:
            assert binding["workspace"]["taskDirectory"] is True
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
            name,
            "Fixture documentation search",
            object_schema({"query": {"type": "string"}}, ["query"]),
            search,
            effect=effect,
            source="external",
            main=True,
        )
    )
    runtime.dispatch.native_executor.workspace_factory = unexpected_workspace
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        await runtime.chat.submit("alice", conversation["id"], "mcp-lookup", request)
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM tasks WHERE state IN ('succeeded','failed','waiting_user')"
            ),
        )
        task = await store.call(
            lambda db: row(db, "SELECT id,state,intent_json,target_json FROM tasks")
        )
        assert task["state"] == ("succeeded" if effect == "read" else "waiting_user")
        if resource_only:
            receipt = await store.call(
                lambda db: row(
                    db,
                    "SELECT payload_json FROM events WHERE task_id=? AND kind=? ORDER BY id DESC LIMIT 1",
                    (task["id"], "task." + task["state"]),
                )
            )
            verification = json.loads(receipt["payload_json"])["result"]["verification"]
            assert verification["state"] == "retrieved"
            assert verification["sources"][0]["url"] == "https://example.org/docs"
            current = await runtime.conversations.accept(
                "alice", conversation["id"], "status", "Task status"
            )
            await store.call(
                lambda db: db.execute(
                    "UPDATE turns SET created_ms=? WHERE id=?",
                    (verification["sources"][0]["retrievedMs"], current["turnId"]),
                ),
                write=True,
            )
            binding = {
                "owner": "alice",
                "conversation": conversation["id"],
                "turnId": current["turnId"],
            }
            status = runtime.tools.registry["task_status"].handler
            snapshot = await status({"taskId": task["id"]}, binding)
            evidence = snapshot[0]["latestAttempt"]["retrievalEvidence"]
            assert evidence["freshForCurrentRequest"] is True
            future = await runtime.conversations.accept(
                "alice", conversation["id"], "new-lookup", request
            )
            await store.call(
                lambda db: db.execute(
                    "UPDATE turns SET created_ms=? WHERE id=?",
                    (evidence["lastRetrievedMs"] + 1, future["turnId"]),
                ),
                write=True,
            )
            snapshot = await status({"taskId": task["id"]}, {**binding, "turnId": future["turnId"]})
            assert (
                snapshot[0]["latestAttempt"]["retrievalEvidence"]["freshForCurrentRequest"] is False
            )
            assert (
                await store.call(
                    lambda db: retrieved_sources(
                        db,
                        {"id": task["id"], "origin_conversation_id": conversation["id"]},
                        {"id": "another-run"},
                        "https://example.org/docs",
                    )
                )
                == []
            )
        assert json.loads(task["intent_json"])["target"].get("resourceOnly", False) == resource_only
        assert invoked == ["public documentation"]
        assert (
            await store.call(
                lambda db: db.execute(
                    "SELECT count(*) FROM tool_calls WHERE tool_name=? AND state='succeeded'",
                    (name,),
                ).fetchone()[0]
            )
            == 1
        )
    finally:
        await runtime.close()


@pytest.mark.parametrize("role", ["worker", "research"])
async def test_background_mcp_discovery_and_call_respect_the_enabled_switch(store, role):
    runtime = Runtime(store, ConversationModel())
    calls = []

    async def search(args, binding):
        calls.append(binding["role"])
        return {"result": "fixture"}

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
    try:
        catalog = await runtime.tools.invoke(
            call("tool_list", {"query": "fixture", "kind": "mcp"}), role, {}
        )
        assert [item["name"] for item in catalog["items"]] == [NAME]
        assert (await runtime.tools.invoke(cli(NAME, {}), role, {"owner": "alice"}))[
            "result"
        ] == "fixture"
        runtime.tools.disabled_tools.add(NAME)
        assert runtime.tools.directory.list("fixture", "mcp", role=role)["items"] == []
        with pytest.raises(DomainError, match="TOOL_DISABLED"):
            await runtime.tools.invoke(cli(NAME, {}), role, {"owner": "alice"})
        assert calls == [role]
    finally:
        await runtime.close()


@pytest.mark.parametrize("role", ["worker", "research"])
async def test_background_skill_discovery_and_loading_respect_the_enabled_switch(
    store, tmp_path, role
):
    package = tmp_path / "skills" / "fixture-workflow"
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text("---\ndescription: Fixture workflow\n---\nFixture skill body")
    runtime = Runtime(
        store, ConversationModel(), settings=Settings(skill_roots=(tmp_path / "skills",))
    )
    try:
        listing = await runtime.tools.invoke(
            call("tool_list", {"query": "fixture-workflow", "kind": "skill"}), role, {}
        )
        assert [item["name"] for item in listing["items"]] == ["fixture-workflow"]
        loaded = await runtime.tools.invoke(
            call("read", {"path": "skill://fixture-workflow"}), role, {}
        )
        assert "Fixture skill body" in loaded["text"]
        runtime.tools.disabled_skills.add("fixture-workflow")
        assert not runtime.tools.directory.list("fixture-workflow", "skill", role=role)["items"]
        with pytest.raises(DomainError, match="SKILL_DISABLED"):
            await runtime.tools.invoke(call("read", {"path": "skill://fixture-workflow"}), role, {})
    finally:
        await runtime.close()
