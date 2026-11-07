"""A real coordinated Main sees its admitted tools without mutating other turns."""

import hashlib
import json

import pytest
from test_foundations import call, cli
from test_swarm_coordination import claim, queue
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row, rows
from roami_agent.tools.foundations import FOUNDATIONS

coordination = coordination_fixture
delegated_team = delegated_team_fixture


async def current(coordination):
    runtime, _, team, _, post, _ = coordination
    await post()
    turn = await claim(runtime, await queue(runtime, team))
    origin = await runtime.journal.origin(turn)
    binding = {
        "owner": "alice",
        "conversation": turn["conversation_id"],
        "turnId": turn["id"],
        "leaseEpoch": turn["lease_epoch"],
        "originMessageId": origin["id"],
        "toolCallId": "directory",
    }
    return runtime, turn, binding


async def test_catalog_projects_real_batch_without_changing_other_main_or_worker(coordination):
    runtime, turn, _ = await current(coordination)
    before = runtime.tools.catalog()
    catalog = await runtime.tools.turn_catalog(turn)
    names = {item["function"]["name"] for item in catalog}
    assert names == {"read", "bash", "tool_list", "ask_user", "reply"}
    bash = next(item["function"] for item in catalog if item["function"]["name"] == "bash")
    assert "Shell and unrelated operations are unavailable" in bash["description"]
    assert runtime.tools.catalog() == before
    assert {item["function"]["name"] for item in before} == set(FOUNDATIONS)
    assert await runtime.tools.turn_catalog(turn, "worker") == runtime.tools.catalog("worker")


async def test_directory_and_help_show_only_scoped_commands_and_argument_choices(coordination):
    runtime, turn, binding = await current(coordination)
    catalog_before = runtime.tools.catalog()
    directory_before = runtime.tools.directory.list()
    result = await runtime.tools.invoke(
        call("tool_list", {"query": "", "kind": "cli"}), "main", binding
    )
    assert result["scope"] == "current_coordination" and "availability" not in result
    group = next(item for item in result["items"] if item["name"] == "roami")
    body = json.dumps(group)
    assert "swarm_status" in body and "task_steer" in body
    assert (
        "session_send" not in body
        and "task_cancel" not in body
        and "capability_install" not in body
    )
    for name, field, expected in [
        ("swarm_project_update", "operation", ["record", "review"]),
        ("swarm_post", "kind", ["progress", "question", "reply"]),
    ]:
        value = await runtime.tools.invoke(call("tool_list", {"query": name}), "main", binding)
        entry = next(item for item in value["items"] if item["name"] == name)
        assert entry["inputSchema"]["properties"][field]["enum"] == expected
    value = await runtime.tools.invoke(call("tool_list", {"query": "task_steer"}), "main", binding)
    entry = next(item for item in value["items"] if item["name"] == "task_steer")
    assert set(entry["inputSchema"]["properties"]) == {"taskId", "text"}
    help_value = await runtime.tools.invoke(
        call("bash", {"command": "roami help"}), "main", binding
    )
    assert help_value["commands"] == group["commands"]
    assert "session_send" not in json.dumps(help_value)
    assert (
        runtime.tools.catalog() == catalog_before
        and runtime.tools.directory.list() == directory_before
    )
    await runtime.tools.turn_catalog(turn)


@pytest.mark.parametrize("command", ["roami session help", "roami chrome help"])
async def test_help_cannot_advertise_unrelated_operations(coordination, command):
    runtime, _, binding = await current(coordination)
    with pytest.raises(DomainError, match="TOOL_UNAVAILABLE"):
        await runtime.tools.invoke(call("bash", {"command": command}), "main", binding)


@pytest.mark.parametrize("change", ["lease", "stop", "forgotten"])
async def test_catalog_and_discovery_recheck_host_admission(coordination, change):
    runtime, turn, binding = await current(coordination)
    if change == "lease":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE turns SET lease_epoch=lease_epoch+1 WHERE id=?", (turn["id"],)
            ),
            write=True,
        )
    elif change == "stop":
        await runtime.chat.interrupt("alice", turn["conversation_id"], "stop")
    else:
        source = await runtime.journal.origin(turn)
        await runtime.db.call(
            lambda db: db.execute(
                "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'forgotten',1)",
                (source["id"],),
            ),
            write=True,
        )
    with pytest.raises(DomainError):
        await runtime.tools.turn_catalog(turn)
    with pytest.raises(DomainError):
        await runtime.tools.invoke(call("tool_list", {}), "main", binding)


async def test_hidden_operation_still_cannot_execute_through_registered_alias(coordination):
    runtime, _, binding = await current(coordination)
    with pytest.raises(DomainError, match="SWARM_COORDINATION_OPERATION_UNAVAILABLE"):
        await runtime.tools.invoke(
            cli("task_cancel", {"taskId": coordination[-1]["taskId"]}), "main", binding
        )


async def test_actual_model_requests_and_manifests_use_the_projected_catalog(coordination):
    runtime, turn, _ = await current(coordination)
    calls = []

    class Model:
        model = "scoped-coordination-catalog"

        async def stream(self, messages, tools):
            calls.append(tools)
            name, args = (
                ("tool_list", {"query": "task_status"})
                if len(calls) == 1
                else ("reply", {"text": "已读取本项目的原成员入口。"})
            )
            yield ModelEvent(
                "tool",
                {
                    "id": "step-" + str(len(calls)),
                    "function": {"name": name, "arguments": json.dumps(args)},
                },
            )

    runtime.model = runtime.loop.model = Model()
    runtime.loop.context.swarms = runtime.loop.context.remembered = None
    await runtime.loop.run(turn, "main")
    assert len(calls) == 2
    assert all(
        {tool["function"]["name"] for tool in catalog}
        == {"read", "bash", "tool_list", "ask_user", "reply"}
        for catalog in calls
    )
    manifests = await runtime.db.call(
        lambda db: rows(
            db,
            "SELECT parts_json FROM prompt_manifests WHERE turn_id=? ORDER BY attempt_no",
            (turn["id"],),
        )
    )
    assert len(manifests) == 2
    assert [json.loads(item["parts_json"])["catalogHash"] for item in manifests] == [
        hashlib.sha256(encoded(catalog).encode()).hexdigest() for catalog in calls
    ]
    assert (
        await runtime.db.call(
            lambda db: row(db, "SELECT state FROM turns WHERE id=?", (turn["id"],))
        )
    )["state"] == "completed"
