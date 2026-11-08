"""Memory edits stay bound to their original Main and stable operation identity."""

import json
import shlex

import pytest
from test_project_okr_conversations import create_goal
from test_project_okr_conversations import project_runtime as project_runtime_fixture
from test_swarm_coordination_policy import coordinated_tools as coordinated_tools_fixture
from test_swarm_coordination_policy import coordination as coordination_fixture
from test_swarm_coordination_policy import delegated_team as delegated_team_fixture
from test_swarm_coordination_policy import invoke

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.swarm_memory import digest
from roami_agent.tools.project_memory_edit import memory_edit_payload, memory_edit_receipt

project_runtime = project_runtime_fixture
coordinated_tools = coordinated_tools_fixture
coordination = coordination_fixture
delegated_team = delegated_team_fixture


def arguments():
    return {"expectedSha256": "a" * 64, "edits": [{"oldText": "old rule", "newText": "new rule"}]}


def response(project_id, key):
    return {
        "projectId": project_id,
        "projectFiles": {
            "memoryEditsSupported": True,
            "teamMemorySha256": "d" * 64,
            "operationReceipt": {
                "key": key,
                "kind": "memory_edit",
                "requestSha256": "b" * 64,
                "previousSha256": "a" * 64,
                "resultSha256": "c" * 64,
                "recordedAt": "2026-11-09T00:00:00Z",
            },
        },
    }


async def test_bound_main_discovers_and_executes_edit_cli_without_selecting_another_project(
    project_runtime, monkeypatch
):
    runtime, _, _ = project_runtime
    cid = (await create_goal(runtime)).json()["data"]["id"]
    calls = []

    async def operation(settings, pid, action, payload=None):
        if action == "show":
            return {"projectFiles": {"memoryEditsSupported": True}}
        calls.append((pid, action, payload))
        return response(pid, payload["operationKey"])

    monkeypatch.setattr("roami_agent.tools.project_memory_edit.operation", operation)
    tool = runtime.tools.registry["project_okr_memory_edit"]
    args = arguments()
    tool.validate(args)
    binding = {"owner": "alice", "conversation": cid, "role": "main", "turnId": "original-turn"}
    listed = await invoke(
        runtime, binding, "tool_list", {"kind": "cli", "query": "project_okr_memory_edit"}
    )
    assert listed["items"][0]["name"] == "project_okr_memory_edit"
    command = shlex.join(["roami", "project", "okr", "memory", "edit", "--input", json.dumps(args)])
    result = await invoke(runtime, binding, "bash", {"command": command})
    assert result["sha256"] == "d" * 64
    assert result["operationReceipt"]["resultSha256"] == "c" * 64
    assert "content" not in result and "projectFiles" not in result
    assert calls[0][0:2] == ("registered", "memory")
    assert calls[0][2]["mode"] == "edit" and calls[0][2]["edits"] == args["edits"]
    for denied in [
        {**binding, "owner": "bob"},
        {**binding, "role": "worker"},
        {**binding, "taskId": "worker-task"},
    ]:
        with pytest.raises(DomainError):
            await tool.handler(args, denied)
    assert len(calls) == 1


async def test_older_host_is_rejected_before_any_memory_write(project_runtime, monkeypatch):
    runtime, _, _ = project_runtime
    cid = (await create_goal(runtime)).json()["data"]["id"]
    calls = []

    async def operation(settings, pid, action, payload=None):
        calls.append(action)
        return {"projectFiles": {}}

    monkeypatch.setattr("roami_agent.tools.project_memory_edit.operation", operation)
    with pytest.raises(DomainError, match="PROJECT_MEMORY_EDIT_UNAVAILABLE"):
        await runtime.tools.registry["project_okr_memory_edit"].handler(
            arguments(), {"owner": "alice", "conversation": cid}
        )
    assert calls == ["show"]


def test_edit_identity_does_not_change_with_new_call_or_fresh_cas():
    original = memory_edit_payload(arguments(), {"turnId": "original-turn", "toolCallId": "one"})
    retry = memory_edit_payload(
        {**arguments(), "expectedSha256": "f" * 64},
        {"turnId": "original-turn", "toolCallId": "two"},
    )
    assert original["operationKey"] == retry["operationKey"]
    with pytest.raises(DomainError, match="MEMORY_EDIT_TURN_REQUIRED"):
        memory_edit_payload(arguments(), {})
    with pytest.raises(DomainError, match="INVALID_MEMORY_EDIT"):
        memory_edit_payload(
            {**arguments(), "edits": [{"oldText": "old", "newText": "\ud800"}]},
            {"turnId": "original-turn"},
        )


@pytest.mark.parametrize(
    "damage", ["wrong-project", "wrong-key", "wrong-kind", "missing-digest", "malformed-files"]
)
def test_receipt_must_match_actual_project_and_edit(damage):
    value = response("project-a", "edit-one")
    if damage == "wrong-project":
        value["projectId"] = "project-b"
    elif damage == "wrong-key":
        value["projectFiles"]["operationReceipt"]["key"] = "another-edit"
    elif damage == "wrong-kind":
        value["projectFiles"]["operationReceipt"]["kind"] = "memory_append"
    elif damage == "missing-digest":
        del value["projectFiles"]["operationReceipt"]["resultSha256"]
    else:
        value["projectFiles"] = []
    with pytest.raises(DomainError, match="PROJECT_MEMORY_EDIT_RECEIPT_UNAVAILABLE"):
        memory_edit_receipt(value, "project-a", "edit-one")


async def test_coordinated_main_uses_pinned_edit_key_through_registered_cli(
    coordinated_tools, monkeypatch
):
    runtime, team, _, _, _, binding = coordinated_tools
    writes = []

    async def execute(argv, **kwargs):
        payload = json.loads(kwargs["input_data"]) if kwargs.get("input_data") else None
        if payload:
            writes.append(payload)
            data = response("project-a", payload["operationKey"])
        else:
            content = "Original knowledge"
            data = {
                "projectId": "project-a",
                "projectFiles": {
                    "memoryEditsSupported": True,
                    "operationReceiptsSupported": True,
                    "teamMemory": content,
                    "teamMemorySha256": digest(content),
                },
            }
        return {"exitCode": 0, "stdout": json.dumps({"data": data})}

    monkeypatch.setattr("roami_agent.storage.swarm_memory.execute", execute)
    batch = await runtime.db.call(
        lambda db: row(
            db, "SELECT id FROM swarm_coordination_batches WHERE turn_id=?", (binding["turnId"],)
        )
    )
    args = {"swarmId": team["id"], **arguments()}
    command = shlex.join(["roami", "swarm", "memory", "edit", "--input", json.dumps(args)])
    result = await invoke(runtime, binding, "bash", {"command": command})
    expected_key = "coordination:" + batch["id"] + ":memory_edit"
    assert result["operationReceipt"]["key"] == expected_key
    assert "outputExternalized" not in result
    await invoke(
        runtime,
        {**binding, "toolCallId": "fresh-call"},
        "swarm_memory_edit",
        {**args, "expectedSha256": "e" * 64},
    )
    assert [item["operationKey"] for item in writes] == [expected_key, expected_key]
    with pytest.raises(DomainError, match="SWARM_COORDINATION_SCOPE_CONFLICT"):
        await invoke(runtime, binding, "swarm_memory_edit", {**args, "swarmId": "foreign-swarm"})
    assert len(writes) == 2

    await runtime.db.call(
        lambda db: db.execute("UPDATE swarm_groups SET archived=1 WHERE id=?", (team["id"],)),
        write=True,
    )
    with pytest.raises(DomainError, match="SWARM_ARCHIVED"):
        await runtime.tools.registry["swarm_memory_edit"].handler(args, binding)
    assert len(writes) == 2
