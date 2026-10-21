"""Live questions route through native Browser Use, not a coding project or legacy session."""

import json
from contextlib import asynccontextmanager

import pytest
from test_browser_driver import BrowserFixture
from test_runtime import until

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


class MemoryModel:
    model = "memory-fixture"

    async def stream(self, messages, tools):
        yield ModelEvent("text", '{"memories":[]}')


async def test_main_web_research_uses_browser_without_configured_code_workspace(store, tmp_path):
    class Main:
        model = "main-research-fixture"

        async def stream(self, messages, tools):
            if messages[-1]["content"] == "Check the latest stock quote":
                yield ModelEvent(
                    "tool",
                    {
                        "id": "research",
                        "function": {
                            "name": "delegate",
                            "arguments": '{"goal":"Check the latest stock quote with sources and time","executor":"native","target":{"kind":"new_session","resourceOnly":true}}',
                        },
                    },
                )
            else:
                yield ModelEvent("text", "Research updates will appear here.")

    class Worker:
        model = "browser-research-fixture"
        step = 0

        async def stream(self, messages, tools):
            self.step += 1
            if self.step == 1:
                seed = messages[-1]["content"]
                assert "Original user request" in seed
                assert "Check the latest stock quote\n\nDelegated goal" in seed
                assert "Check the latest stock quote with sources and time" in seed
                name, args = "tool_list", {"query": "browser_use"}
            elif self.step == 2:
                name, args = "read", {"path": "skill://browser_use"}
            elif self.step == 3:
                name, args = "browser_act", {}
            elif self.step == 4:
                name, args = "browser_open", {"url": "https://example.org/quote"}
            else:
                yield ModelEvent(
                    "text",
                    "Observed the quote source https://example.org/quote. This is fixture data, not a real price.",
                )
                return
            yield ModelEvent(
                "tool",
                {
                    "id": f"read-{self.step}",
                    "function": {
                        "name": name if name in {"read", "tool_list"} else "bash",
                        "arguments": json.dumps(
                            args
                            if name in {"read", "tool_list"}
                            else {
                                "argv": [
                                    "roami",
                                    "agent",
                                    "capability",
                                    "call",
                                    name,
                                    "--input",
                                    json.dumps(args),
                                ]
                            }
                        ),
                    },
                },
            )

    fixture = BrowserFixture()
    runtime = Runtime(
        store,
        Main(),
        worker_model=Worker(),
        memory_model=MemoryModel(),
        settings=Settings(browser={"enabled": True}, coding_directory=tmp_path),
    )
    runtime.browser.runner = fixture

    async def receipt(operation):
        return fixture.receipts[operation]

    @asynccontextmanager
    async def forbidden_workspace(*args, **kwargs):
        pytest.fail("A web lookup must not prepare a code workspace")
        yield

    runtime.browser.receipt_reader = receipt
    runtime.dispatch.native_executor.workspace_factory = forbidden_workspace
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        await runtime.chat.submit(
            "alice", conversation["id"], "quote", "Check the latest stock quote"
        )
        await until(store, lambda db: row(db, "SELECT * FROM tasks WHERE state='succeeded'"))
        task = await store.call(lambda db: row(db, "SELECT * FROM tasks WHERE state='succeeded'"))
        assert json.loads(task["intent_json"])["target"] == {
            "kind": "new_session",
            "resourceOnly": True,
        }
        assert json.loads(task["intent_json"])["executor"] == "native"
        assert fixture.url == "https://example.org/quote"
        assert "new" in fixture.writes and "goto" in fixture.writes
        view = await runtime.conversations.messages("alice", conversation["id"])
        assert not any(activity["kind"] == "tool" for activity in view["activities"])
        records = await runtime.tasks.activities("alice", task["id"])
        assert any(activity.get("name") == "browser_open" for activity in records)
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "target,executor",
    [
        ({"kind": "project", "projectId": "p", "resourceOnly": True}, "native"),
        ({"kind": "new_session", "directory": "/tmp", "resourceOnly": True}, "native"),
        ({"kind": "new_session", "resourceOnly": True}, "codex"),
    ],
)
async def test_resource_only_cannot_override_project_or_coding_workspace(store, target, executor):
    runtime = Runtime(store, MemoryModel())
    conversation = await runtime.conversations.create("alice")
    with pytest.raises(DomainError, match="INVALID_RESOURCE_ONLY_TARGET"):
        await runtime.tasks.create(
            "alice", conversation["id"], "lookup", key="bad", target=target, executor=executor
        )


async def test_disabled_browser_is_discovered_and_never_blindly_enqueued(store):
    runtime = Runtime(store, MemoryModel())
    overview = await runtime.tools.registry["capability_overview"].handler({}, {})
    assert overview["webResearchAvailable"] is False
    with pytest.raises(DomainError, match="WEB_RESEARCH_UNAVAILABLE"):
        await runtime.tools.registry["web_research"].handler({"goal": "latest quote"}, {})
    assert await store.call(lambda db: db.execute("SELECT count(*) FROM tasks").fetchone()[0]) == 0


async def test_research_catalog_and_invocation_deny_non_navigation_tools(store):
    runtime = Runtime(store, MemoryModel(), settings=Settings(browser={"enabled": True}))
    catalog = runtime.tools.catalog("research")
    assert {tool["function"]["name"] for tool in catalog} == {"read", "bash", "tool_list"}
    commands = runtime.tools.directory.list("browser", "cli", 10, "research")["items"]
    assert {item["name"] for item in commands} == {"roami chrome"}
    forms = [item["argv"][2] for item in commands[0]["commands"]]
    assert "goto" in forms and "click" not in forms
    for name, args in [
        ("shell", {"argv": ["echo", "forbidden"]}),
        ("browser_act", {"kind": "click", "observationId": "scene", "selector": "#buy"}),
        ("browser_open", {"targetId": "user-owned"}),
        ("skill_read", {"name": "roami"}),
    ]:
        with pytest.raises(DomainError, match="TOOL_UNAVAILABLE"):
            await runtime.tools.invoke(
                {"function": {"name": name, "arguments": json.dumps(args)}}, "research", {}
            )
