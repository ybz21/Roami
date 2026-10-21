import json

import pytest
from test_browser_driver import BrowserFixture, BrowserModel, native_browser
from test_runtime import ConversationModel, until

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


def bash(*argv):
    return {"function": {"name": "bash", "arguments": json.dumps({"argv": ["roami", *argv]})}}


async def test_public_browser_commands_keep_task_receipts_and_verified_results(store, monkeypatch):
    class PublicBrowserModel(BrowserModel):
        async def stream(self, messages, tools):
            async for event in super().stream(messages, tools):
                if event.kind != "tool":
                    yield event
                    continue
                wire = event.value
                function = wire["function"]
                args = json.loads(function["arguments"])
                if function["name"] == "browser_open":
                    argv = ["chrome", "new", args["url"]]
                else:
                    argv = ["chrome", args["kind"], args["selector"]]
                    if "text" in args:
                        argv.append(args["text"])
                    argv += ["--observation", args["observationId"]]
                yield ModelEvent("tool", {**wire, **bash(*argv)})

    monkeypatch.setattr("test_browser_driver.BrowserModel", PublicBrowserModel)
    fixture = BrowserFixture()
    runtime, _, task = await native_browser(store, fixture)
    try:
        await until(
            store,
            lambda db: (
                row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],))["state"] == "succeeded"
            ),
        )
        assert fixture.saved and fixture.name == "Roami"
        assert fixture.writes == ["new", "goto", "fill", "click"]
        actions = await store.call(
            lambda db: db.execute(
                "SELECT state FROM resource_actions WHERE task_id=?", (task["id"],)
            ).fetchall()
        )
        assert len(actions) == 4 and all(action["state"] == "succeeded" for action in actions)
    finally:
        await runtime.close()


async def test_named_memory_command_uses_owner_scope_and_real_read_effect(store):
    runtime = Runtime(store, ConversationModel())
    conversation = await runtime.conversations.create("alice")
    binding = {"owner": "alice", "conversation": conversation["id"]}
    wire = bash("agent", "memory", "search", "--input", '{"query":"fixture"}')
    tool, args = runtime.tools.validate(wire, "main")
    assert tool.name == "memory_search" and tool.effect == "read"
    assert args == {"query": "fixture"}
    result = await runtime.tools.invoke(wire, "main", binding)
    assert result["hits"] == []
    assert (
        await runtime.tools.invoke(
            bash("agent", "task", "status", "--input", "{}"), "main", binding
        )
        == []
    )


async def test_research_help_and_public_commands_cannot_expand_role(store):
    runtime = Runtime(store, ConversationModel(), settings=Settings(browser={"enabled": True}))
    help_result = await runtime.tools.invoke(bash("chrome", "help"), "research", {})
    assert help_result["name"] == "roami chrome"
    assert not any(command["argv"][2] == "click" for command in help_result["commands"])
    for argv in [
        ("chrome", "click", "#buy", "--observation", "scene"),
        ("chrome", "observe", "--target", "user-tab"),
        ("chrome", "eval", "document.cookie"),
        ("chrome", "new", "https://example.com", "--cdp", "http://another-node"),
        ("agent", "memory", "search", "--input", '{"query":"private"}'),
    ]:
        with pytest.raises(DomainError):
            await runtime.tools.invoke(bash(*argv), "research", {})


async def test_builtin_aliases_read_current_content_without_duplicate_entries(store):
    runtime = Runtime(store, ConversationModel())
    for old, new in [
        ("roami-dispatch", "roami"),
        ("web-research", "browser_use"),
        ("roami-dispatch/references/chrome.md", "browser_use/references/chrome-cli.md"),
    ]:

        def read(name):
            return {
                "function": {"name": "read", "arguments": json.dumps({"path": "skill://" + name})}
            }

        assert await runtime.tools.invoke(read(old), "main", {}) == await runtime.tools.invoke(
            read(new), "main", {}
        )
    assert set(runtime.tools.skills) == {"roami", "browser_use"}
    with pytest.raises(DomainError, match="CAPABILITY_ALREADY_EXISTS"):
        await runtime.capability_imports.save(
            "local", "skills", {"name": "web-research", "text": "replacement"}
        )
