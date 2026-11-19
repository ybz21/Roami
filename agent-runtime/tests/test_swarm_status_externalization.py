import json

import pytest

from roami_agent.protocol.tools import Tool
from roami_agent.storage.artifact_store import ArtifactStore
from roami_agent.tools.registry import Tools


@pytest.mark.parametrize("name", ["swarm_status", "other_read"])
async def test_large_status_keeps_current_control_state_and_exact_history_artifact(store, name):
    artifacts = ArtifactStore(store)
    tools = Tools(artifacts)
    value = {
        "id": "original-swarm",
        "revision": 59,
        "paused": True,
        "archived": False,
        "mainState": "completed",
        "mainConversationId": "original-main",
        "sequence": 42,
        "mainMessages": [{"text": "historical message " * 10000}],
        "members": [{"id": "original-member"}],
    }

    async def read(arguments, binding):
        return value

    tools.add(Tool(name, "Read current state", {"type": "object"}, read, main=True))
    result = await tools.invoke(
        {"id": "read-state", "function": {"name": name, "arguments": "{}"}},
        "main",
        {"owner": "alice"},
    )
    assert result["outputExternalized"] is True
    assert len(json.dumps(result)) < 10000
    for key in ["revision", "paused", "archived", "mainState", "mainConversationId", "sequence"]:
        if name == "swarm_status":
            assert result[key] == value[key]
        else:
            assert key not in result
    assert "mainMessages" not in result and "members" not in result
    content = (await artifacts.read("alice", result["artifactRefs"][0]["id"]))[1]
    assert json.loads(content) == value
