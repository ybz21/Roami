"""Accepted bounded work retains real user provenance and is fenced before dispatch."""

import json
from contextlib import asynccontextmanager

import pytest
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_coordination_policy import coordinated_tools as coordinated_tools_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture
from test_swarm_delegations import finish

from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.protocol.errors import DomainError, ToolPreflightError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row

coordinated_tools = coordinated_tools_fixture
coordination = coordination_fixture
delegated_team = delegated_team_fixture

ASSIGNMENT = "只整理本轮数据候选和原始证据，不发布内容，不自行验收，不接管Main。"


@pytest.fixture
async def continuing_member(coordinated_tools, tmp_path):
    runtime, team, enabled, _question, actor, binding = coordinated_tools
    folder = tmp_path / "promotion"
    folder.mkdir()

    async def project_workspace(project):
        assert project == "project-a"
        return {"projectId": project, "directory": str(folder)}

    runtime.tasks.revisions.project_workspace = project_workspace
    await runtime.db.call(
        lambda db: (
            db.execute(
                "UPDATE task_attempts SET session_id='original-session',agent_conversation_id='provider-original' WHERE id=?",
                (actor["runId"],),
            ),
            db.execute(
                "UPDATE tasks SET target_json=? WHERE id=?",
                (
                    json.dumps(
                        {
                            "sessionId": "original-session",
                            "workdir": str(folder),
                            "workspace": {"directory": str(folder)},
                        }
                    ),
                    actor["taskId"],
                ),
            ),
        ),
        write=True,
    )
    await runtime.tasks.report(
        "alice",
        actor["taskId"],
        actor["runId"],
        1,
        {
            "state": "succeeded",
            "summary": "Existing evidence",
            "outcomeKnown": True,
            "inputStopped": True,
        },
    )
    verification = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='task.verify' AND aggregate_id=?", (actor["taskId"],)
        )
    )
    await runtime.dispatch.verify(verification)
    return runtime, team, enabled, actor, binding, folder, project_workspace


async def request(data, **kwargs):
    runtime, _, _, actor, binding, _, _ = data
    return await runtime.tasks.revisions.request(
        "alice",
        actor["taskId"],
        ASSIGNMENT,
        1,
        "bounded",
        source_turn_id=binding["turnId"],
        source_conversation_id=binding["conversation"],
        source_lease_epoch=binding["leaseEpoch"],
        **kwargs,
    )


async def operation(runtime, receipt):
    return await runtime.db.call(
        lambda db: row(db, "SELECT * FROM jobs WHERE id=?", (receipt["operationId"],))
    )


async def finish_main(data):
    runtime, _, _, _, binding, _, _ = data
    turn = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?",
            (binding["turnId"],),
        )
    )
    await finish(runtime, turn)


async def revoke(data):
    runtime, _, enabled, _, binding, _, _ = data
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE swarm_goal_delegations SET revoked_ms=1,revoked_by_message_id=? WHERE id=?",
            (binding["originMessageId"], enabled["delegationId"]),
        ),
        write=True,
    )


async def test_finished_main_handoff_keeps_original_member_task_provider_and_goal_source(
    continuing_member,
):
    runtime, team, _, actor, binding, _, _ = continuing_member
    before = await runtime.db.call(
        lambda db: [
            db.execute("SELECT count(*) FROM " + table).fetchone()[0]
            for table in ["conversations", "tasks", "swarm_members"]
        ]
    )
    receipt = await request(continuing_member)
    assert (
        await runtime.tasks.revisions.request(
            "alice",
            actor["taskId"],
            ASSIGNMENT,
            1,
            "a-different-call-key",
            source_turn_id=binding["turnId"],
            source_conversation_id=binding["conversation"],
            source_lease_epoch=binding["leaseEpoch"],
        )
        == receipt
    )
    payload = json.loads((await operation(runtime, receipt))["payload_json"])
    source = await runtime.db.call(
        lambda db: row(db, "SELECT content_json FROM messages WHERE id=?", (payload["messageId"],))
    )
    content = json.loads(source["content_json"])
    assert content["text"] == ASSIGNMENT and content["instructionAuthor"] == "main"
    assert content["sourceUserMessageId"] == binding["originMessageId"]
    assert payload["coordinationAuthorization"]["goalQuote"] != ASSIGNMENT
    await finish_main(continuing_member)
    await runtime.tasks.revisions.advance()
    applied = await runtime.tasks.revisions.get("alice", actor["taskId"], receipt["operationId"])
    assert applied["state"] == "applied" and applied["revision"] == 2
    task = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (actor["taskId"],))
    )
    intent = json.loads(task["intent_json"])
    assert intent["target"]["sessionId"] == "original-session"
    assert intent["continuation"]["providerRunId"] == actor["runId"]
    assert intent["coordinationAuthorization"] == payload["coordinationAuthorization"]
    assert "coordinationAuthorization" not in intent["initialIntent"]
    assert (
        await runtime.db.call(
            lambda db: [
                db.execute("SELECT count(*) FROM " + table).fetchone()[0]
                for table in ["conversations", "tasks", "swarm_members"]
            ]
        )
        == before
    )
    assert (
        await runtime.swarms.member(
            "alice", team["id"], payload["coordinationAuthorization"]["memberId"]
        )
    )["member"]["taskId"] == actor["taskId"]


@pytest.mark.parametrize("change", ["revoked", "forgotten", "stop", "directory", "unknown"])
async def test_delayed_steer_rechecks_authority_and_stop_proof_before_new_revision(
    continuing_member, change, tmp_path
):
    runtime, _, _, actor, binding, _, _ = continuing_member
    prior = await runtime.db.call(
        lambda db: row(db, "SELECT revision,state FROM tasks WHERE id=?", (actor["taskId"],))
    )
    receipt = await request(continuing_member)
    if change == "revoked":
        await revoke(continuing_member)
    elif change == "forgotten":
        await runtime.db.call(
            lambda db: db.execute(
                "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'forgotten',1)",
                (binding["originMessageId"],),
            ),
            write=True,
        )
    elif change == "stop":
        await runtime.chat.interrupt("alice", binding["conversation"], "stop")
    elif change == "directory":

        async def changed(project):
            return {"projectId": project, "directory": str(tmp_path / "changed")}

        runtime.tasks.revisions.project_workspace = changed
    else:
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE task_attempts SET result_json=? WHERE id=?",
                (json.dumps({"outcomeKnown": False, "inputStopped": True}), actor["runId"]),
            ),
            write=True,
        )
    await runtime.tasks.revisions.advance()
    actual = await runtime.tasks.revisions.get("alice", actor["taskId"], receipt["operationId"])
    assert actual["state"] == "blocked" and actual["errorCode"]
    task = await runtime.db.call(
        lambda db: row(db, "SELECT revision,state FROM tasks WHERE id=?", (actor["taskId"],))
    )
    assert task == prior


async def test_paused_goal_keeps_same_pending_operation_until_resume(continuing_member):
    runtime, team, _, actor, _, _, _ = continuing_member
    receipt = await request(continuing_member)
    current = await runtime.swarms.snapshot("alice", team["id"], include_memory=False)
    paused = await runtime.swarms.control(
        "alice",
        team["id"],
        {"commandKey": "pause", "expectedRevision": current["revision"], "action": "pause"},
    )
    await runtime.tasks.revisions.advance()
    assert (await operation(runtime, receipt))["state"] == "queued"
    await runtime.swarms.control(
        "alice",
        team["id"],
        {"commandKey": "resume", "expectedRevision": paused["revision"], "action": "resume"},
    )
    await runtime.tasks.revisions.advance()
    actual = await runtime.tasks.revisions.get("alice", actor["taskId"], receipt["operationId"])
    assert actual["state"] == "applied" and actual["operationId"] == receipt["operationId"]


async def test_revocation_during_project_lookup_leaves_no_late_steer_or_instruction(
    continuing_member,
):
    runtime, _, _, _, _, _, getter = continuing_member

    async def changed(project):
        await revoke(continuing_member)
        return await getter(project)

    runtime.tasks.revisions.project_workspace = changed
    before = await runtime.db.call(
        lambda db: [
            db.execute("SELECT count(*) FROM " + table).fetchone()[0]
            for table in ["jobs", "messages"]
        ]
    )
    with pytest.raises(DomainError, match="SWARM_DELEGATION_REQUIRED"):
        await request(continuing_member)
    assert (
        await runtime.db.call(
            lambda db: [
                db.execute("SELECT count(*) FROM " + table).fetchone()[0]
                for table in ["jobs", "messages"]
            ]
        )
        == before
    )


async def test_source_quote_cannot_expand_the_original_delegated_goal(continuing_member):
    with pytest.raises(DomainError, match="TASK_STEER_SOURCE_REQUIRED"):
        await request(continuing_member, source_quote="无需确认即可发布所有账号")


async def test_revoked_accepted_revision_does_not_reach_cli_launch_or_become_unknown(
    continuing_member,
):
    runtime, _, _, _actor, _, _, getter = continuing_member
    receipt = await request(continuing_member)
    await finish_main(continuing_member)
    await runtime.tasks.revisions.advance()
    applied = json.loads((await operation(runtime, receipt))["payload_json"])
    await revoke(continuing_member)
    launched = []
    executor = CodingExecutor(runtime.db, Settings())
    executor.project_workspace = getter

    async def command(*args, **kwargs):
        launched.append(args)
        raise AssertionError("Revoked work reached real transport")

    executor.command = command
    runtime.dispatch.executor = executor
    job = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT * FROM jobs WHERE kind='task.run' AND json_extract(payload_json,'$.runId')=?",
            (applied["runId"],),
        )
    )
    await runtime.dispatch.run(job)
    assert not launched
    result = await runtime.db.call(
        lambda db: row(
            db, "SELECT state,result_json FROM task_attempts WHERE id=?", (applied["runId"],)
        )
    )
    body = json.loads(result["result_json"])
    assert result["state"] != "unknown" and body["executionStarted"] is False
    assert body["summary"] == "SWARM_DELEGATION_REQUIRED"


async def test_cli_preparation_rechecks_revocation_after_async_directory_lookup(continuing_member):
    runtime, _, _, actor, _, _, getter = continuing_member
    receipt = await request(continuing_member)
    await runtime.tasks.revisions.advance()
    applied = json.loads((await operation(runtime, receipt))["payload_json"])
    task = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (actor["taskId"],))
    )
    run = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE id=?", (applied["runId"],))
    )
    executor = CodingExecutor(runtime.db, Settings())

    async def changed(project):
        await revoke(continuing_member)
        return await getter(project)

    executor.project_workspace = changed

    async def command(*args, **kwargs):
        raise AssertionError("A late launch passed goal admission")

    executor.command = command
    with pytest.raises(ToolPreflightError, match="SWARM_DELEGATION_REQUIRED"):
        await executor.launch(task, run, {"sessionId": "original-session"})


async def test_real_core_reads_fresh_task_and_appends_one_bounded_original_member_round(
    continuing_member,
):
    runtime, _, _, actor, binding, _, _ = continuing_member

    class Model:
        model = "controlled-bounded-steer"
        stage = 0

        async def stream(self, messages, tools):
            self.stage += 1
            if self.stage == 1:
                name, args = (
                    "bash",
                    {
                        "argv": [
                            "roami",
                            "agent",
                            "task",
                            "status",
                            "--input",
                            json.dumps({"taskId": actor["taskId"]}),
                        ]
                    },
                )
            elif self.stage == 2:
                name, args = (
                    "bash",
                    {
                        "argv": [
                            "roami",
                            "agent",
                            "task",
                            "steer",
                            "--input",
                            json.dumps({"taskId": actor["taskId"], "text": ASSIGNMENT}),
                        ]
                    },
                )
            else:
                name, args = "reply", {"text": "已交给原数据成员补齐候选，尚待核验。"}
            yield ModelEvent(
                "tool",
                {
                    "id": "steer-" + str(self.stage),
                    "function": {"name": name, "arguments": json.dumps(args)},
                },
            )

    runtime.model = runtime.loop.model = Model()
    runtime.loop.context.swarms = None
    runtime.loop.context.remembered = None
    turn = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?",
            (binding["turnId"],),
        )
    )
    await runtime.loop.run(turn, "main")
    job = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='task.steer' AND aggregate_id=?", (actor["taskId"],)
        )
    )
    payload = json.loads(job["payload_json"])
    assert payload["expectedRevision"] == 1 and payload["executionText"] == ASSIGNMENT
    assert payload["coordinationAuthorization"]["mainTurnId"] == binding["turnId"]
    assert runtime.loop.model.stage == 3
    await runtime.tasks.revisions.advance()
    actual = await runtime.tasks.revisions.get("alice", actor["taskId"], job["id"])
    assert actual["state"] == "applied" and actual["revision"] == 2


@pytest.mark.parametrize("delegated_team", ["native"], indirect=True)
@pytest.mark.parametrize("change", [None, "revoked", "paused", "paused_after_bind", "directory"])
async def test_native_continuation_keeps_original_branch_and_rechecks_after_workspace_prepare(
    continuing_member, change
):
    runtime, team, _, actor, _, folder, getter = continuing_member
    original = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE id=?", (actor["runId"],))
    )
    branch = original["native_branch_id"]
    before = await runtime.db.call(
        lambda db: db.execute("SELECT count(*) FROM conversations").fetchone()[0]
    )
    assert original["executor_kind"] == "native" and branch
    receipt = await request(continuing_member)
    await finish_main(continuing_member)
    await runtime.tasks.revisions.advance()
    applied = json.loads((await operation(runtime, receipt))["payload_json"])
    run = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE id=?", (applied["runId"],))
    )
    assert run["native_branch_id"] == branch
    calls = []

    class Worker:
        model = "controlled-native-continuation"

        async def stream(self, messages, tools):
            calls.append(messages)
            yield ModelEvent("text", "候选和证据已整理，等待 Main 独立验收。")

    async def pause():
        current = await runtime.swarms.snapshot("alice", team["id"], include_memory=False)
        await runtime.swarms.control(
            "alice",
            team["id"],
            {
                "commandKey": "late-pause",
                "expectedRevision": current["revision"],
                "action": "pause",
            },
        )

    lookups = 0

    async def project_workspace(project):
        nonlocal lookups
        lookups += 1
        if change == "paused_after_bind" and lookups == 2:
            await pause()
        return await getter(project)

    @asynccontextmanager
    async def workspace(*args, **kwargs):
        if change == "revoked":
            await revoke(continuing_member)
        elif change == "paused":
            await pause()
        yield {
            "workspaceId": "original-workspace",
            "directory": str(folder / "changed" if change == "directory" else folder),
            "projectId": "project-a",
        }

    runtime.loop.worker_model = Worker()
    runtime.loop.context.swarms = None
    runtime.loop.context.remembered = None
    runtime.dispatch.native_executor.workspace_factory = workspace
    runtime.dispatch.native_executor.project_workspace = project_workspace
    job = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT * FROM jobs WHERE kind='task.run' AND json_extract(payload_json,'$.runId')=?",
            (run["id"],),
        )
    )
    await runtime.dispatch.run(job)
    latest = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE id=?", (run["id"],))
    )
    assert latest["native_branch_id"] == branch
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM conversations").fetchone()[0]
        )
        == before
    )
    if change in {"paused", "paused_after_bind"}:
        assert not calls and latest["state"] == "accepted" and latest["result_json"] is None
        current = await runtime.swarms.snapshot("alice", team["id"], include_memory=False)
        await runtime.swarms.control(
            "alice",
            team["id"],
            {
                "commandKey": "resume-native",
                "expectedRevision": current["revision"],
                "action": "resume",
            },
        )
        change = None
        await runtime.dispatch.run(job)
        latest = await runtime.db.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE id=?", (run["id"],))
        )
    if change in {"revoked", "directory"}:
        assert not calls and latest["state"] != "unknown"
        result = json.loads(latest["result_json"])
        assert result["executionStarted"] is False
        assert result["summary"] == (
            "SWARM_DELEGATION_REQUIRED"
            if change == "revoked"
            else "SWARM_COORDINATION_WORKSPACE_CHANGED"
        )
        target = await runtime.db.call(
            lambda db: row(db, "SELECT target_json FROM tasks WHERE id=?", (actor["taskId"],))
        )
        assert json.loads(target["target_json"])["workdir"] == str(folder)
    else:
        assert len(calls) == 1
        assert ASSIGNMENT in str(calls[0])
        assert (
            json.loads(latest["result_json"])["summary"] == "候选和证据已整理，等待 Main 独立验收。"
        )
        assert (
            await runtime.db.call(
                lambda db: db.execute(
                    "SELECT count(*) FROM events WHERE event_key=?", ("workspace:" + run["id"],)
                ).fetchone()[0]
            )
            == 1
        )
