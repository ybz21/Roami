"""Resolved tool aliases cannot escape the original project's coordination scope."""

import json
from dataclasses import replace

import pytest
from test_swarm_coordination import claim, queue
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.database import row

coordination = coordination_fixture
delegated_team = delegated_team_fixture


@pytest.fixture
async def coordinated_tools(coordination):
    runtime, service, team, enabled, post, actor = coordination
    source = await service.current("alice", team["id"])
    question = await post()
    turn = await claim(runtime, await queue(runtime, team))
    binding = {
        "owner": "alice",
        "conversation": team["mainConversationId"],
        "turnId": turn["id"],
        "leaseEpoch": turn["lease_epoch"],
        "originMessageId": source["source_message_id"],
        "toolCallId": "tool",
    }
    return runtime, team, enabled, question, actor, binding


async def invoke(runtime, binding, name, args):
    return await runtime.tools.invoke(
        {"function": {"name": name, "arguments": json.dumps(args)}}, "main", binding
    )


async def test_original_main_can_reply_once_via_actual_registered_cli_alias(coordinated_tools):
    runtime, team, _, question, actor, binding = coordinated_tools
    args = {
        "swarmId": team["id"],
        "kind": "reply",
        "replyTo": question["id"],
        "text": "使用本项目已确认口径",
    }
    before = await runtime.db.call(
        lambda db: row(db, "SELECT state,revision FROM tasks WHERE id=?", (actor["taskId"],))
    )
    call = {"argv": ["roami", "swarm", "post", "--input", json.dumps(args)]}
    result = await invoke(runtime, binding, "bash", call)
    assert (
        await invoke(runtime, {**binding, "toolCallId": "retry-new-call"}, "bash", call) == result
    )
    member = await runtime.swarms.inbox("alice", team["id"], {}, binding=actor)
    assert len(member["items"]) == 1 and member["items"][0]["replyTo"] == question["id"]
    assert (
        await runtime.db.call(
            lambda db: row(db, "SELECT state,revision FROM tasks WHERE id=?", (actor["taskId"],))
        )
        == before
    )


@pytest.mark.parametrize("kind", ["progress", "question"])
async def test_progress_cannot_shadow_the_host_reply_business_key(coordinated_tools, kind):
    runtime, team, _, question, actor, binding = coordinated_tools
    batch = await runtime.db.call(
        lambda db: row(
            db, "SELECT id FROM swarm_coordination_batches WHERE turn_id=?", (binding["turnId"],)
        )
    )
    source = (await runtime.swarms.inbox("alice", team["id"], {}))["items"][0]
    note = {
        "swarmId": team["id"],
        "kind": kind,
        "messageKey": "coordination:" + batch["id"] + ":reply:" + str(question["id"]),
        "text": "只记录本轮进展",
    }
    if kind == "question":
        note["recipientMemberId"] = source["authorMemberId"]
    progress = await invoke(runtime, binding, "swarm_post", note)
    assert (
        await invoke(runtime, {**binding, "toolCallId": "note-retry"}, "swarm_post", note)
        == progress
    )
    reply = await invoke(
        runtime,
        {**binding, "toolCallId": "actual-answer"},
        "swarm_post",
        {
            "swarmId": team["id"],
            "kind": "reply",
            "replyTo": question["id"],
            "text": "使用已经确认的来源",
        },
    )
    member = await runtime.swarms.inbox("alice", team["id"], {}, binding=actor)
    assert any(
        item["postId"] == reply["id"] and item["replyTo"] == question["id"]
        for item in member["items"]
    )


async def test_same_message_key_cannot_change_kind_and_recipient_on_retry(coordinated_tools):
    runtime, team, _, _, _, binding = coordinated_tools
    source = (await runtime.swarms.inbox("alice", team["id"], {}))["items"][0]
    args = {
        "swarmId": team["id"],
        "kind": "progress",
        "messageKey": "one-business-message",
        "text": "本轮进展",
    }
    await invoke(runtime, binding, "swarm_post", args)
    with pytest.raises(DomainError, match="SWARM_MESSAGE_KEY_CONFLICT"):
        await invoke(
            runtime,
            {**binding, "toolCallId": "changed-kind"},
            "swarm_post",
            {**args, "kind": "question", "recipientMemberId": source["authorMemberId"]},
        )


@pytest.mark.parametrize(
    "operation",
    [
        "shell",
        "foreign_swarm",
        "unselected_member",
        "other_task",
        "new_roles",
        "steer",
        "configuration",
    ],
)
async def test_coordinator_cannot_escape_to_arbitrary_execution_or_resources(
    coordinated_tools, tmp_path, operation
):
    runtime, team, _, _, actor, binding = coordinated_tools
    marker = tmp_path / "unexpected-write"
    calls = {
        "shell": ("bash", {"command": "touch " + str(marker)}),
        "foreign_swarm": ("swarm_status", {"swarmId": "foreign"}),
        "unselected_member": ("swarm_member", {"swarmId": team["id"], "memberId": "foreign"}),
        "other_task": ("task_status", {"taskId": "foreign"}),
        "new_roles": (
            "swarm_members_register",
            {
                "swarmId": team["id"],
                "expectedRevision": 3,
                "members": [
                    {"name": "Replacement", "executor": "codex", "duty": "Replace original"}
                ],
            },
        ),
        "steer": (
            "task_steer",
            {"taskId": actor["taskId"], "revision": 1, "text": "Continue", "requestComplete": True},
        ),
        "configuration": (
            "swarm_project_update",
            {"swarmId": team["id"], "operation": "save", "payload": {}},
        ),
    }
    name, args = calls[operation]
    with pytest.raises(DomainError, match="SWARM_COORDINATION_"):
        await invoke(runtime, binding, name, args)
    assert not marker.exists()


async def test_task_status_is_limited_to_the_selected_original_tasks(coordinated_tools):
    runtime, _, _, _, actor, binding = coordinated_tools
    result = await invoke(runtime, binding, "task_status", {"taskId": actor["taskId"]})
    assert actor["taskId"] in json.dumps(result)
    with pytest.raises(DomainError, match="SWARM_COORDINATION_SCOPE_CONFLICT"):
        await invoke(runtime, binding, "task_status", {})


async def test_artifact_alias_rejects_other_owner_scoped_files_before_reading(coordinated_tools):
    runtime, _, _, _, actor, binding = coordinated_tools
    foreign = await runtime.artifacts.put(
        "alice", b"OTHER_PRIVATE_ARTIFACT", mime_type="text/plain", name="private.txt"
    )
    with pytest.raises(DomainError, match="SWARM_COORDINATION_SCOPE_CONFLICT"):
        await invoke(runtime, binding, "read", {"path": "artifact://" + foreign["id"]})
    current = await runtime.artifacts.put(
        "alice",
        b"CURRENT_RUN_EVIDENCE",
        mime_type="text/plain",
        name="evidence.txt",
        task_id=actor["taskId"],
        metadata={"runId": actor["runId"]},
    )
    result = await invoke(runtime, binding, "read", {"path": "artifact://" + current["id"]})
    assert result["text"] == "CURRENT_RUN_EVIDENCE"


async def test_file_read_uses_host_project_root_and_ignores_supplied_workspace(
    coordinated_tools, tmp_path, monkeypatch
):
    runtime, _, _, _, _, binding = coordinated_tools
    folder = tmp_path / "project"
    folder.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    (folder / "AGENTS.md").write_text("ACTUAL_PROJECT_RULES")
    (other / "private.txt").write_text("FOREIGN_PROJECT_PRIVATE")
    targets = runtime.tools.admission.__self__.targets

    async def query(*args):
        assert args == ("project", "show", "project-a", "--json")
        return {"data": {"key": "project-a", "name": "Project", "dir": str(folder)}}

    monkeypatch.setattr(targets, "_query", query)
    supplied = {**binding, "workspace": {"directory": str(other)}}
    result = await invoke(runtime, supplied, "read", {"path": "AGENTS.md"})
    assert result["data"] == "ACTUAL_PROJECT_RULES"
    with pytest.raises(DomainError, match="WORKSPACE_OUTSIDE_CONFIGURED_ROOTS"):
        await invoke(runtime, supplied, "read", {"path": str(other / "private.txt")})


async def test_host_directory_change_during_read_withholds_old_root_bytes(
    coordinated_tools, tmp_path, monkeypatch
):
    runtime, _, _, _, _, binding = coordinated_tools
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "AGENTS.md").write_text("OLD_ROOT_CONTENT")
    calls = 0

    async def query(*args):
        nonlocal calls
        calls += 1
        return {
            "data": {
                "key": "project-a",
                "name": "Project",
                "dir": str(first if calls == 1 else second),
            }
        }

    monkeypatch.setattr(runtime.tools.admission.__self__.targets, "_query", query)
    with pytest.raises(DomainError, match="SWARM_COORDINATION_WORKSPACE_CHANGED"):
        await invoke(runtime, binding, "read", {"path": "AGENTS.md"})


async def test_a_read_revoked_while_running_does_not_return_its_bytes(coordinated_tools):
    runtime, _, enabled, _, actor, binding = coordinated_tools
    current = await runtime.artifacts.put(
        "alice",
        b"WITHHELD_AFTER_REVOCATION",
        mime_type="text/plain",
        name="evidence.txt",
        task_id=actor["taskId"],
        metadata={"runId": actor["runId"]},
    )
    original = runtime.tools.registry["artifact_read"]

    async def revoke_after_read(args, supplied):
        result = await original.handler(args, supplied)
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE swarm_goal_delegations SET revoked_ms=1,revoked_by_message_id=? WHERE id=?",
                (binding["originMessageId"], enabled["delegationId"]),
            ),
            write=True,
        )
        return result

    runtime.tools.registry["artifact_read"] = replace(original, handler=revoke_after_read)
    with pytest.raises(DomainError, match="SWARM_DELEGATION_REQUIRED"):
        await invoke(runtime, binding, "read", {"path": "artifact://" + current["id"]})


@pytest.mark.parametrize(
    "change", [{"leaseEpoch": -1}, {"originMessageId": "member-text"}, {"conversation": "Home"}]
)
async def test_binding_flags_cannot_substitute_the_host_batch_identity(coordinated_tools, change):
    runtime, team, _, _, _, binding = coordinated_tools
    with pytest.raises(DomainError):
        await invoke(runtime, {**binding, **change}, "swarm_status", {"swarmId": team["id"]})


@pytest.mark.parametrize("private_roundtrip", [False, True])
async def test_real_core_processes_host_batch_in_original_main_without_a_new_user_turn(
    coordinated_tools,
    private_roundtrip,
):
    runtime, team, _, question, actor, binding = coordinated_tools
    if private_roundtrip:
        original = runtime.tools.registry["swarm_post"]
        forwarding = False

        async def through_private_context(args, supplied):
            nonlocal forwarding
            if forwarding:
                return await original.handler(args, supplied)
            forwarding = True
            try:
                return await runtime.cli_commands.call(
                    "swarm_post",
                    {
                        "turnId": supplied["turnId"],
                        "toolCallId": supplied["toolCallId"],
                        "arguments": args,
                    },
                    supplied["owner"],
                )
            finally:
                forwarding = False

        runtime.tools.registry["swarm_post"] = replace(original, handler=through_private_context)

    class Model:
        model = "controlled-coordination"
        stage = 0

        async def stream(self, messages, tools):
            self.stage += 1
            if self.stage == 1:
                name = "bash"
                args = {
                    "argv": [
                        "roami",
                        "swarm",
                        "post",
                        "--input",
                        json.dumps(
                            {
                                "swarmId": team["id"],
                                "kind": "reply",
                                "replyTo": question["id"],
                                "text": "使用本项目原目标约定的取数口径。",
                            }
                        ),
                    ]
                }
            else:
                name, args = "reply", {"text": "已答复原数据成员，任务仍待独立验收。"}
            yield ModelEvent(
                "tool",
                {
                    "id": "call-" + str(self.stage),
                    "function": {"name": name, "arguments": json.dumps(args)},
                },
            )

    model = Model()
    runtime.model = runtime.loop.model = model
    runtime.loop.context.swarms = None
    runtime.loop.context.remembered = None
    turn = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?",
            (binding["turnId"],),
        )
    )
    before = await runtime.db.call(
        lambda db: [
            db.execute("SELECT count(*) FROM " + table).fetchone()[0]
            for table in ["conversations", "tasks", "swarm_members"]
        ]
    )
    await runtime.loop.run(turn, "main")
    result = await runtime.db.call(
        lambda db: row(db, "SELECT state FROM turns WHERE id=?", (turn["id"],))
    )
    assert result["state"] == "completed" and model.stage == 2
    planned = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT arguments_json FROM tool_calls WHERE turn_id=? AND tool_name='swarm_post'",
            (turn["id"],),
        )
    )
    route = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT message_key FROM swarm_post_routes WHERE reply_to_post_id=? AND author_kind='main'",
            (question["id"],),
        )
    )
    assert json.loads(planned["arguments_json"])["messageKey"] == route["message_key"]
    inbox = await runtime.swarms.inbox("alice", team["id"], {}, binding=actor)
    assert inbox["items"][0]["replyTo"] == question["id"]
    assert (await runtime.swarms.inbox("alice", team["id"], {}))["items"] == []
    assert (
        await runtime.db.call(
            lambda db: db.execute(
                "SELECT count(*) FROM messages WHERE turn_id=? AND role='user'", (turn["id"],)
            ).fetchone()[0]
        )
        == 0
    )
    assert (
        await runtime.db.call(
            lambda db: [
                db.execute("SELECT count(*) FROM " + table).fetchone()[0]
                for table in ["conversations", "tasks", "swarm_members"]
            ]
        )
        == before
    )
