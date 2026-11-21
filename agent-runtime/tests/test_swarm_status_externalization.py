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
        "memberYieldSupported": True,
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
    for key in [
        "revision",
        "paused",
        "archived",
        "mainState",
        "mainConversationId",
        "sequence",
        "memberYieldSupported",
    ]:
        if name == "swarm_status":
            assert result[key] == value[key]
        else:
            assert key not in result
    assert "mainMessages" not in result and "members" not in result
    content = (await artifacts.read("alice", result["artifactRefs"][0]["id"]))[1]
    assert json.loads(content) == value


async def test_large_history_keeps_original_selected_run_visible_without_trusting_reports(store):
    artifacts = ArtifactStore(store)
    tools = Tools(artifacts)
    value = {
        "id": "original-swarm",
        "mainMessages": [{"text": "retired reports " * 20000}],
        "members": [
            {"id": ident, "taskId": ident + "-task", "state": "running"}
            for ident in ("retired", "original")
        ],
        "work": [
            {
                "id": ident + "-work",
                "memberId": ident,
                "task_id": ident + "-task",
                "revision": 5,
                "state": "waiting_user",
                "attempt": {
                    "runId": ident + "-run",
                    "state": "unknown",
                    "summary": "I published successfully " * 10000,
                },
            }
            for ident in ("retired", "original")
        ],
    }

    async def read(arguments, binding):
        return value

    async def admission(tool, args, binding, *, after=False):
        return args, {**binding, "coordinationMemberIds": ["original"]}

    tools.admission = admission
    tools.add(Tool("swarm_status", "Status", {"type": "object"}, read, main=True))
    result = await tools.invoke(
        {"function": {"name": "swarm_status", "arguments": "{}"}},
        "main",
        {"owner": "alice"},
    )
    current = result["overview"]
    assert current["selection"] == "admitted_goal_members"
    assert current["members"]["items"] == [value["members"][1]]
    assert current["work"]["items"] == [
        {
            "id": "original-work",
            "memberId": "original",
            "task_id": "original-task",
            "revision": 5,
            "state": "waiting_user",
            "attempt": {"runId": "original-run", "state": "unknown"},
        }
    ]
    assert len(json.dumps(result).encode()) < 10000
    assert "task_status" in current["details"]["tasks"]
    content = (await artifacts.read("alice", result["artifactRefs"][0]["id"]))[1]
    assert json.loads(content) == value


def test_status_overview_has_a_byte_budget_and_explicit_incomplete_page():
    from roami_agent.tools.swarm_status_overview import overview

    value = {
        "members": [{"id": str(i), "name": "历史成员" * 80} for i in range(100)],
        "work": [
            {"id": str(i), "memberId": str(i), "task_id": "original-" + str(i)} for i in range(1000)
        ],
    }
    result = overview(value)
    assert result["selection"] == "registered_members"
    assert result["members"]["total"] == 100 and result["members"]["hasMore"]
    assert result["work"]["total"] == 1000 and result["work"]["hasMore"]
    assert len(json.dumps(result, ensure_ascii=False).encode()) < 16000
    assert result["members"]["items"][0]["name"] == value["members"][0]["name"]
