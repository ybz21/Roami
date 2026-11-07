import pytest
from test_swarm_coordination import claim, queue
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_coordination import delegated_team as delegated_team_fixture
from test_swarm_delegations import GOAL, finish

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.swarm_coordination import admitted_batch
from roami_agent.storage.swarm_inbox_wakeup import advance

coordination = coordination_fixture
delegated_team = delegated_team_fixture


async def notification(runtime, post_id):
    return await runtime.db.call(
        lambda db: row(
            db,
            "SELECT j.* FROM jobs j JOIN swarm_inbox i ON i.id=json_extract(j.payload_json,'$.inboxId') "
            "WHERE j.kind='swarm.inbox.wakeup' AND i.post_id=?",
            (post_id,),
        )
    )


async def step(runtime, job_id):
    return await runtime.db.call(lambda db: advance(db, job_id), write=True)


async def test_member_question_wakes_original_main_before_execution_result(coordination):
    runtime, _, team, _, post, actor = coordination
    question = await post()
    job = await notification(runtime, question["id"])
    assert job
    result = await step(runtime, job["id"])
    assert result["handled"] is False
    assert await step(runtime, job["id"]) == result
    actual = await runtime.db.call(lambda db: admitted_batch(db, "alice", result["turnId"]))
    assert actual["conversation_id"] == team["mainConversationId"]
    assert actual["inputs"][0]["postId"] == question["id"]
    assert not actual["results"]
    assert await runtime.db.call(
        lambda db: row(db, "SELECT result_json FROM task_attempts WHERE id=?", (actor["runId"],))
    ) == {"result_json": None}
    inbox = await runtime.db.call(
        lambda db: row(
            db, "SELECT handled_post_id FROM swarm_inbox WHERE post_id=?", (question["id"],)
        )
    )
    assert inbox["handled_post_id"] is None


async def test_already_frozen_question_does_not_create_another_batch(coordination):
    runtime, _, team, _, post, _ = coordination
    question = await post()
    batch = await queue(runtime, team)
    job = await notification(runtime, question["id"])
    actual = await step(runtime, job["id"])
    assert actual["batchId"] == batch["batchId"]
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_coordination_batches").fetchone()[0]
        )
        == 1
    )


async def test_busy_main_keeps_same_question_notification(coordination):
    runtime, _, team, _, post, _ = coordination
    accepted = await runtime.conversations.accept(
        "alice", team["mainConversationId"], "foreground", "先等我补充当前目标"
    )
    foreground = await claim(runtime, {"turnId": accepted["turnId"]})
    question = await post()
    job = await notification(runtime, question["id"])
    assert (await step(runtime, job["id"]))["waiting"] == "MAIN_BUSY"
    await finish(runtime, foreground)
    assert (await step(runtime, job["id"]))["batchId"]


@pytest.mark.parametrize("action", ["pause", "stale", "revoke"])
async def test_question_notification_revalidates_scope_and_state(coordination, action):
    runtime, service, team, _, post, actor = coordination
    question = await post()
    job = await notification(runtime, question["id"])
    if action == "pause":
        revision = await runtime.db.call(
            lambda db: db.execute(
                "SELECT revision FROM swarm_groups WHERE id=?", (team["id"],)
            ).fetchone()[0]
        )
        await runtime.swarms.control(
            "alice",
            team["id"],
            {"commandKey": "pause", "expectedRevision": revision, "action": "pause"},
        )
        assert (await step(runtime, job["id"]))["waiting"] == "SWARM_COORDINATION_PAUSED"
    elif action == "stale":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE tasks SET revision=revision+1 WHERE id=?", (actor["taskId"],)
            ),
            write=True,
        )
        assert (await step(runtime, job["id"]))["skipped"] == "source_not_current"
    else:
        accepted = await runtime.conversations.accept(
            "alice", team["mainConversationId"], "revoke", "停止这个持续目标"
        )
        turn = await claim(runtime, {"turnId": accepted["turnId"]})
        await service.revoke(
            "alice",
            team["id"],
            {"commandKey": "revoke", "expectedDelegationRevision": 1},
            binding={
                "conversation": team["mainConversationId"],
                "turnId": turn["id"],
                "leaseEpoch": turn["lease_epoch"],
            },
        )
        assert (await step(runtime, job["id"]))["skipped"] == "SWARM_DELEGATION_REQUIRED"
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_coordination_batches").fetchone()[0]
        )
        == 0
    )


async def test_progress_and_human_discussion_do_not_supply_member_execution_authority(coordination):
    runtime, _, team, _, post, _ = coordination
    progress = await post(kind="progress")
    assert await notification(runtime, progress["id"]) is None
    human = await runtime.swarms.post(
        "alice", team["id"], {"commandKey": "human", "text": "讨论目标", "kind": "question"}
    )
    assert await notification(runtime, human["id"]) is None


async def test_message_and_notification_commit_or_roll_back_together(coordination, monkeypatch):
    runtime, _, _, _, post, _ = coordination
    before = await runtime.db.call(
        lambda db: db.execute("SELECT count(*) FROM swarm_posts").fetchone()[0]
    )

    def fail(*args):
        raise DomainError("STORAGE_FAILED")

    monkeypatch.setattr("roami_agent.storage.swarm_inbox_wakeup.queue_post", fail)
    with pytest.raises(DomainError, match="STORAGE_FAILED"):
        await post()
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_posts").fetchone()[0]
        )
        == before
    )


async def test_source_stop_wins_before_user_turn_state_finishes(coordination):
    runtime, service, team, enabled, post, _ = coordination
    accepted = await runtime.conversations.accept(
        "alice", team["mainConversationId"], "new-goal", GOAL
    )
    turn = await claim(runtime, {"turnId": accepted["turnId"]})
    await service.enable(
        "alice",
        team["id"],
        {
            "commandKey": "new-goal",
            "sourceQuote": GOAL,
            "expectedDelegationRevision": 1,
            "memberIds": enabled["memberIds"],
        },
        binding={
            "conversation": team["mainConversationId"],
            "turnId": turn["id"],
            "leaseEpoch": turn["lease_epoch"],
        },
    )
    question = await post()
    job = await notification(runtime, question["id"])
    await runtime.chat.interrupt("alice", team["mainConversationId"], "stop-goal-source")
    assert (await step(runtime, job["id"]))["skipped"] == "SWARM_DELEGATION_SOURCE_STOPPED"


async def test_paused_question_notification_runs_after_resume_with_same_identity(coordination):
    runtime, _, team, _, post, _ = coordination
    question = await post()
    job = await notification(runtime, question["id"])
    revision = await runtime.db.call(
        lambda db: db.execute(
            "SELECT revision FROM swarm_groups WHERE id=?", (team["id"],)
        ).fetchone()[0]
    )
    paused = await runtime.swarms.control(
        "alice",
        team["id"],
        {"commandKey": "pause", "expectedRevision": revision, "action": "pause"},
    )
    assert (await step(runtime, job["id"]))["waiting"] == "SWARM_COORDINATION_PAUSED"
    await runtime.swarms.control(
        "alice",
        team["id"],
        {"commandKey": "resume", "expectedRevision": paused["revision"], "action": "resume"},
    )
    assert (await step(runtime, job["id"]))["batchId"]
    assert (await notification(runtime, question["id"]))["id"] == job["id"]


async def test_bounded_backlog_retains_late_question_notification(coordination):
    runtime, _, _, _, post, _ = coordination
    questions = [await post(key=str(index)) for index in range(23)]
    job = await notification(runtime, questions[-1]["id"])
    assert (await step(runtime, job["id"]))["waiting"] == "bounded_backlog"
    first = await runtime.db.call(
        lambda db: row(db, "SELECT id AS batchId,turn_id AS turnId FROM swarm_coordination_batches")
    )
    current = await claim(runtime, first)
    await finish(runtime, current)
    delivered = await step(runtime, job["id"])
    assert delivered["batchId"] != first["batchId"]
    actual = await runtime.db.call(lambda db: admitted_batch(db, "alice", delivered["turnId"]))
    assert questions[-1]["id"] in {item["postId"] for item in actual["inputs"]}


async def test_answered_question_is_not_reinjected(coordination):
    runtime, _, team, _, post, _ = coordination
    question = await post()
    job = await notification(runtime, question["id"])
    batch = await queue(runtime, team)
    turn = await claim(runtime, batch)
    await runtime.swarms.post(
        "alice",
        team["id"],
        {
            "commandKey": "answer",
            "kind": "reply",
            "replyTo": question["id"],
            "text": "按已确认口径执行",
        },
        binding={
            "conversation": team["mainConversationId"],
            "turnId": turn["id"],
            "leaseEpoch": turn["lease_epoch"],
        },
    )
    assert (await step(runtime, job["id"]))["skipped"] == "source_not_current"
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_coordination_batches").fetchone()[0]
        )
        == 1
    )
