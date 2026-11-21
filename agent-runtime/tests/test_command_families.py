import json

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError


def bash(*argv):
    return {"function": {"name": "bash", "arguments": json.dumps({"argv": ["roami", *argv]})}}


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
    assert set(runtime.tools.skills) == {"roami", "browser_use", "okr-development"}
    with pytest.raises(DomainError, match="CAPABILITY_ALREADY_EXISTS"):
        await runtime.capability_imports.save(
            "local", "skills", {"name": "web-research", "text": "replacement"}
        )
