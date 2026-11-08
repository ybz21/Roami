from dataclasses import replace

import pytest
from test_swarm_coordination_policy import coordinated_tools as coordinated_tools_fixture
from test_swarm_coordination_policy import coordination as coordination_fixture
from test_swarm_coordination_policy import delegated_team as delegated_team_fixture
from test_swarm_coordination_policy import invoke

from roami_agent.protocol.errors import DomainError

coordinated_tools = coordinated_tools_fixture
coordination = coordination_fixture
delegated_team = delegated_team_fixture


@pytest.mark.parametrize("alias", ["project_okr_context", "bash"])
async def test_common_project_read_reuses_original_goal_scope(
    coordinated_tools, monkeypatch, alias
):
    runtime, _, _, _, _, binding = coordinated_tools
    calls = []

    async def operation(settings, pid, action, payload=None):
        calls.append((pid, action, payload))
        return {"revision": 7, "projectFiles": {"teamMemorySha256": "a" * 64}}

    monkeypatch.setattr("roami_agent.tools.project_okr.operation", operation)
    args = (
        {}
        if alias == "project_okr_context"
        else {"command": "roami project okr context --input '{}'"}
    )
    result = await invoke(runtime, binding, alias, args)
    assert result["projectId"] == "project-a" and result["revision"] == 7
    assert calls == [("project-a", "show", None)]
    directory = await invoke(runtime, binding, "tool_list", {"query": "project_okr_context"})
    assert any(item["name"] == "project_okr_context" for item in directory["items"])


async def test_project_binding_change_before_read_cannot_cross_the_goal(
    coordinated_tools, monkeypatch
):
    runtime, _, _, _, _, binding = coordinated_tools
    original = runtime.tools.registry["project_okr_context"]
    calls = []

    async def operation(*args):
        calls.append(args)
        raise AssertionError("other project must not be read")

    async def changed(args, supplied):
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE project_okr_conversations SET project_id='project-b' WHERE conversation_id=?",
                (binding["conversation"],),
            ),
            write=True,
        )
        return await original.handler(args, supplied)

    monkeypatch.setattr("roami_agent.tools.project_okr.operation", operation)
    runtime.tools.registry[original.name] = replace(original, handler=changed)
    with pytest.raises(DomainError, match="SWARM_COORDINATION_SCOPE_CONFLICT"):
        await invoke(runtime, binding, "project_okr_context", {})
    assert calls == []


async def test_model_cannot_select_project_or_broaden_read_into_writes(
    coordinated_tools, monkeypatch
):
    runtime, _, _, _, _, binding = coordinated_tools
    calls = []

    async def operation(*args):
        calls.append(args)
        raise AssertionError("forbidden operation")

    monkeypatch.setattr("roami_agent.tools.project_okr.operation", operation)
    with pytest.raises(DomainError):
        await invoke(runtime, binding, "project_okr_context", {"projectId": "project-b"})
    with pytest.raises(DomainError, match="SWARM_COORDINATION_OPERATION_UNAVAILABLE"):
        await invoke(runtime, binding, "project_okr_update", {"operation": "save", "payload": {}})
    with pytest.raises(DomainError, match="SWARM_COORDINATION_OPERATION_UNAVAILABLE"):
        await invoke(runtime, binding, "bash", {"command": "ls -la /tmp"})
    assert calls == []
