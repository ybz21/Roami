import pytest
from test_swarm_delegations import delegated_team as delegated_team_fixture
from test_swarm_delegations import finish

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.swarm_coordination import admitted_batch, evidence
from roami_agent.storage.swarm_goal_start import advance

delegated_team = delegated_team_fixture


async def step(runtime, job_id):
    return await runtime.db.call(lambda db: advance(db, job_id), write=True)


async def test_initial_goal_waits_for_real_user_turn_and_replays_one_original_main_batch(
    delegated_team,
):
    runtime, service, team, _, turn, binding, spec = delegated_team
    first = await service.enable("alice", team["id"], spec, binding=binding, bootstrap=True)
    assert await service.enable("alice", team["id"], spec, binding=binding, bootstrap=True) == first
    assert (await step(runtime, first["startJobId"]))["waiting"] == "MAIN_BUSY"
    await finish(runtime, turn)
    result = await step(runtime, first["startJobId"])
    assert result["delegationId"] == first["delegationId"]
    assert await step(runtime, first["startJobId"]) == result
    actual = await runtime.db.call(lambda db: admitted_batch(db, "alice", result["turnId"]))
    assert actual["conversation_id"] == team["mainConversationId"]
    assert actual["inputs"] == actual["results"] == []
    assert actual["initialGoal"] is True and evidence(actual)["initialGoal"] is True
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_coordination_batches").fetchone()[0]
        )
        == 1
    )
    assert not await runtime.db.call(
        lambda db: row(
            db, "SELECT id FROM messages WHERE turn_id=? AND role='user'", (result["turnId"],)
        )
    )


@pytest.mark.parametrize("change", ["stop", "revoke", "forget", "archive"])
async def test_start_cannot_outlive_its_source(delegated_team, change):
    runtime, service, team, _, _, binding, spec = delegated_team
    enabled = await service.enable("alice", team["id"], spec, binding=binding, bootstrap=True)
    if change == "stop":
        await runtime.chat.interrupt("alice", team["mainConversationId"], "stop")
    elif change == "revoke":
        await service.revoke(
            "alice",
            team["id"],
            {"commandKey": "revoke", "expectedDelegationRevision": 1},
            binding=binding,
        )
    elif change == "forget":
        await runtime.db.call(
            lambda db: db.execute(
                "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) "
                "SELECT 'alice',source_message_id,'forgotten',1 FROM swarm_goal_delegations WHERE id=?",
                (enabled["delegationId"],),
            ),
            write=True,
        )
    elif change == "archive":
        await runtime.swarms.control(
            "alice",
            team["id"],
            {"commandKey": "archive", "expectedRevision": 2, "action": "archive"},
        )
    result = await step(runtime, enabled["startJobId"])
    assert result.get("skipped")
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_coordination_batches").fetchone()[0]
        )
        == 0
    )


async def test_committed_goal_survives_a_failed_final_reply(delegated_team):
    runtime, service, team, _, turn, binding, spec = delegated_team
    enabled = await service.enable("alice", team["id"], spec, binding=binding, bootstrap=True)
    await runtime.journal.fail(turn, "failed", "MODEL_FAILED")
    assert (await step(runtime, enabled["startJobId"]))["batchId"]


async def test_paused_initial_notification_keeps_its_identity_until_resume(delegated_team):
    runtime, service, team, _, turn, binding, spec = delegated_team
    enabled = await service.enable("alice", team["id"], spec, binding=binding, bootstrap=True)
    paused = await runtime.swarms.control(
        "alice", team["id"], {"commandKey": "pause", "expectedRevision": 2, "action": "pause"}
    )
    await finish(runtime, turn)
    assert (await step(runtime, enabled["startJobId"]))["waiting"] == "SWARM_COORDINATION_PAUSED"
    await runtime.swarms.control(
        "alice",
        team["id"],
        {"commandKey": "resume", "expectedRevision": paused["revision"], "action": "resume"},
    )
    assert (await step(runtime, enabled["startJobId"]))["batchId"]


async def test_goal_and_initial_notification_roll_back_together(delegated_team, monkeypatch):
    runtime, service, team, _, _, binding, spec = delegated_team

    def fail(*args):
        raise DomainError("STORAGE_FAILED")

    monkeypatch.setattr("roami_agent.storage.swarm_goal_start.queue_start", fail)
    with pytest.raises(DomainError, match="STORAGE_FAILED"):
        await service.enable("alice", team["id"], spec, binding=binding, bootstrap=True)
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_goal_delegations").fetchone()[0]
        )
        == 0
    )
