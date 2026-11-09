import json
from dataclasses import replace

import pytest
from test_swarm_coordination_policy import coordinated_tools as coordinated_tools_fixture
from test_swarm_coordination_policy import coordination as coordination_fixture
from test_swarm_coordination_policy import delegated_team as delegated_team_fixture
from test_swarm_coordination_policy import invoke
from test_swarm_goal_continuity import Reviewer
from test_swarm_goal_continuity import delivery as delivery_fixture

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row

coordination = coordination_fixture
delegated_team = delegated_team_fixture
coordinated_tools = coordinated_tools_fixture
delivery = delivery_fixture


@pytest.fixture
async def idle_delivery(delivery, tmp_path, monkeypatch):
    runtime, binding, actor = delivery
    folder = tmp_path / "project"
    folder.mkdir()

    async def workspace(project):
        assert project == "project-a"
        return {"projectId": project, "directory": str(folder)}

    runtime.tasks.revisions.project_workspace = workspace
    targets = runtime.tools.admission.__self__.targets

    async def query(*args):
        return {"data": {"key": "project-a", "name": "Project", "dir": str(folder)}}

    monkeypatch.setattr(targets, "_query", query)

    def ended(db):
        db.execute(
            "UPDATE task_attempts SET state='succeeded',finished_ms=1 "
            "WHERE task_id IN (SELECT id FROM tasks WHERE origin_conversation_id=?)",
            (binding["conversation"],),
        )
        db.execute(
            "UPDATE tasks SET state='succeeded' WHERE origin_conversation_id=?",
            (binding["conversation"],),
        )
        db.execute(
            "UPDATE tasks SET target_json=? WHERE id=?",
            (
                json.dumps({"workdir": str(folder), "workspace": {"directory": str(folder)}}),
                actor["taskId"],
            ),
        )

    await runtime.db.call(ended, write=True)
    runtime.reply_review = Reviewer(True)
    return runtime, binding, actor


async def reply(runtime, binding):
    return await invoke(runtime, binding, "reply", {"text": "本批已经验收，下一轮另行安排。"})


async def test_real_final_reply_rejects_idle_ongoing_goal_without_ending_its_turn(idle_delivery):
    runtime, binding, _ = idle_delivery
    with pytest.raises(DomainError, match="SWARM_GOAL_NEXT_STEP_REQUIRED"):
        await reply(runtime, binding)
    turn = await runtime.db.call(
        lambda db: row(db, "SELECT state FROM turns WHERE id=?", (binding["turnId"],))
    )
    assert turn["state"] == "running"


async def test_direct_text_path_checks_the_same_guard(idle_delivery):
    runtime, binding, _ = idle_delivery
    turn = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?",
            (binding["turnId"],),
        )
    )
    code = await runtime.gateway.reply_error(
        {**turn, "finalReplyCandidate": True}, "本批已经验收，下一轮另行安排。"
    )
    assert code == "SWARM_GOAL_NEXT_STEP_REQUIRED"
    assert await runtime.gateway.reply_error(turn, "先读取任务状态。") is None


async def test_finite_goal_can_finish_without_creating_new_work(idle_delivery):
    runtime, binding, _ = idle_delivery
    runtime.reply_review = Reviewer(False)
    result = await reply(runtime, binding)
    assert "reply" in result
    recorded = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT receipt_json FROM swarm_commands WHERE command_key LIKE 'goal-checkpoint:%'",
        )
    )
    assert json.loads(recorded["receipt_json"])["decision"]["kind"] == "reviewed_no_next_step"


async def test_actual_pending_steer_allows_reply_and_keeps_original_identity(idle_delivery):
    runtime, binding, actor = idle_delivery
    with pytest.raises(DomainError, match="SWARM_GOAL_NEXT_STEP_REQUIRED"):
        await reply(runtime, binding)
    receipt = await runtime.tasks.revisions.request(
        "alice",
        actor["taskId"],
        "继续原任务，仅取下一批真实数据。",
        1,
        "next-original-work",
        source_turn_id=binding["turnId"],
        source_conversation_id=binding["conversation"],
        source_lease_epoch=binding["leaseEpoch"],
    )
    result = await reply(runtime, binding)
    assert "reply" in result
    record = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT receipt_json FROM swarm_commands WHERE command_key LIKE 'goal-checkpoint:%'",
        )
    )
    checkpoint = json.loads(record["receipt_json"])
    assert any(
        step.get("jobId") == receipt["operationId"] for step in checkpoint["decision"]["steps"]
    )


async def test_blocker_needs_a_real_allowed_current_turn_failure(idle_delivery):
    runtime, binding, _ = idle_delivery
    team = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT swarm_id FROM swarm_coordination_batches WHERE turn_id=?",
            (binding["turnId"],),
        )
    )
    args = {
        "swarmId": team["swarm_id"],
        "reason": "工作区暂时无法读取。",
        "failedToolCallId": "missing",
    }
    with pytest.raises(DomainError, match="SWARM_GOAL_BLOCKER_EVIDENCE_REQUIRED"):
        await invoke(runtime, binding, "swarm_goal_checkpoint", args)

    async def unavailable(args, binding):
        raise DomainError("WORKSPACE_READ_UNAVAILABLE", 503)

    runtime.tools.registry["file_read"] = replace(
        runtime.tools.registry["file_read"], handler=unavailable
    )
    turn = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?",
            (binding["turnId"],),
        )
    )
    mid = await runtime.journal.start(turn)
    call = {
        "id": "actual-read",
        "type": "function",
        "function": {"name": "read", "arguments": json.dumps({"path": "AGENTS.md"})},
    }
    failed = await runtime.gateway.invoke(
        turn, mid, call, "main", {**binding, "toolCallId": "actual-read"}
    )
    assert failed["error"] == "WORKSPACE_READ_UNAVAILABLE"
    args["failedToolCallId"] = "actual-read"
    proposal = await invoke(runtime, binding, "swarm_goal_checkpoint", args)
    assert proposal["goalComplete"] is False
    assert "reply" in await reply(runtime, binding)


@pytest.mark.parametrize("direct", [False, True])
async def test_real_core_repairs_idle_reply_in_same_turn_with_one_original_handoff(
    idle_delivery, direct
):
    from roami_agent.protocol.models import ModelEvent

    runtime, binding, actor = idle_delivery

    class Model:
        model = "controlled-goal-follow-through"
        stage = 0

        async def stream(self, messages, tools):
            self.stage += 1
            if self.stage == 1:
                if direct:
                    yield ModelEvent("text", "本批已经验收，下一轮另行安排。")
                    return
                name, args = "reply", {"text": "本批已经验收，下一轮另行安排。"}
            elif self.stage == 2:
                assert any(
                    m.get("role") == "tool"
                    and "SWARM_GOAL_NEXT_STEP_REQUIRED" in str(m.get("content"))
                    for m in messages
                )
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
            elif self.stage == 3:
                name, args = (
                    "bash",
                    {
                        "argv": [
                            "roami",
                            "agent",
                            "task",
                            "steer",
                            "--input",
                            json.dumps(
                                {
                                    "taskId": actor["taskId"],
                                    "text": "继续原任务，补齐下一批真实数据。",
                                }
                            ),
                        ]
                    },
                )
            else:
                assert self.stage == 4
                name, args = "reply", {"text": "已交给原数据成员补齐候选，尚待核验。"}
            yield ModelEvent(
                "tool",
                {
                    "id": "goal-step-" + str(self.stage),
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
    state = await runtime.db.call(
        lambda db: {
            "turn": row(db, "SELECT state FROM turns WHERE id=?", (turn["id"],)),
            "jobs": list(
                db.execute(
                    "SELECT payload_json FROM jobs WHERE kind='task.steer' AND aggregate_id=?",
                    (actor["taskId"],),
                )
            ),
            "checkpoint": row(
                db,
                "SELECT receipt_json FROM swarm_commands WHERE command_key LIKE 'goal-checkpoint:%'",
            ),
        }
    )
    assert state["turn"]["state"] == "completed"
    assert len(state["jobs"]) == 1
    job = json.loads(state["jobs"][0][0])
    assert job["coordinationAuthorization"]["taskId"] == actor["taskId"]
    assert job["coordinationAuthorization"]["sourceRunId"] == actor["runId"]
    assert (
        json.loads(state["checkpoint"]["receipt_json"])["decision"]["kind"]
        == "waiting_for_original_work"
    )
    assert runtime.loop.model.stage == 4


async def test_resumed_main_rechecks_snapshot_without_repeating_original_handoff(idle_delivery):
    runtime, binding, actor = idle_delivery
    receipt = await runtime.tasks.revisions.request(
        "alice",
        actor["taskId"],
        "继续原任务，补齐下一批真实数据。",
        1,
        "accepted-before-resume",
        source_turn_id=binding["turnId"],
        source_conversation_id=binding["conversation"],
        source_lease_epoch=binding["leaseEpoch"],
    )
    await reply(runtime, binding)
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE turns SET lease_epoch=lease_epoch+1 WHERE id=?", (binding["turnId"],)
        ),
        write=True,
    )
    resumed = {**binding, "leaseEpoch": binding["leaseEpoch"] + 1}
    assert "reply" in await reply(runtime, resumed)
    with pytest.raises(DomainError, match="SWARM_COORDINATION_NOT_CURRENT"):
        await reply(runtime, binding)
    data = await runtime.db.call(
        lambda db: {
            "jobs": list(
                db.execute(
                    "SELECT id FROM jobs WHERE kind='task.steer' AND aggregate_id=?",
                    (actor["taskId"],),
                )
            ),
            "proofs": list(
                db.execute(
                    "SELECT receipt_json FROM swarm_commands WHERE command_key LIKE 'goal-checkpoint:%'"
                )
            ),
        }
    )
    assert [r[0] for r in data["jobs"]] == [receipt["operationId"]]
    assert {json.loads(r[0])["leaseEpoch"] for r in data["proofs"]} == {1, 2}
    await runtime.tasks.revisions.advance()
    current = await runtime.tasks.revisions.get("alice", actor["taskId"], receipt["operationId"])
    assert current["state"] == "applied" and current["revision"] == 2
