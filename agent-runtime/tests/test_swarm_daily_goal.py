import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from test_runtime import until
from test_swarm_delegations import delegated_team as delegated_team_fixture
from test_swarm_delegations import finish

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.swarm_coordination import admitted_batch, evidence, record_retrieval
from roami_agent.storage.swarm_daily_goal import advance, queue
from roami_agent.tools.swarm_coordination_policy import SwarmCoordinationPolicy

delegated_team = delegated_team_fixture
DAY = datetime.now(ZoneInfo("Asia/Shanghai")).replace(hour=9, minute=0, second=0, microsecond=0)


async def test_daily_guidance_names_only_tools_in_the_real_batch_catalog(delegated_team):
    runtime, service, team, _, initial, binding, spec = delegated_team
    goal = await service.enable("alice", team["id"], spec, binding=binding)
    await finish(runtime, initial)
    dated = await step(runtime, await tick(runtime, team, goal, slot="review"))
    job = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?", (dated["turnId"],)
        )
    )
    turn = await runtime.mailbox.claim(job)
    plan, prompt = await runtime.loop.context.build(turn, "Review the actual day.", [], None)
    assert plan["coordinationEvidence"]["dailySlot"]["slot"] == "review"
    coordination = [
        m["content"]
        for m in prompt
        if m["role"] == "system"
        and m["content"].startswith("Current original-Main coordination batch")
    ]
    assert len(coordination) == 1
    instructions = coordination[0].split("Trusted batch metadata and quoted source data:", 1)[0]
    named = {
        name
        for name in runtime.tools.registry
        if "_" in name
        and re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", instructions)
    }
    assert named
    admitted = await SwarmCoordinationPolicy(runtime.db, None).tool_names(turn, "main")
    assert named <= admitted | {"read", "bash"}


async def tick(runtime, team, goal, *, slot="morning", timezone="Asia/Shanghai", clock=None):
    return await runtime.db.call(
        lambda db: queue(
            db,
            "alice",
            team["id"],
            goal["delegationId"],
            slot=slot,
            timezone=timezone,
            clock=clock or DAY,
        ),
        write=True,
    )


async def step(runtime, job):
    return await runtime.db.call(
        lambda db: advance(db, job["jobId"], clock=DAY),
        write=True,
    )


async def test_daily_slot_keeps_original_main_user_source_and_replays_one_batch(delegated_team):
    runtime, service, team, source, turn, binding, spec = delegated_team
    goal = await service.enable("alice", team["id"], spec, binding=binding)
    first = await tick(runtime, team, goal)
    assert await tick(runtime, team, goal) == first
    assert (await step(runtime, first))["waiting"] == "MAIN_BUSY"
    await finish(runtime, turn)
    result = await step(runtime, first)
    assert await step(runtime, first) == result
    batch = await runtime.db.call(lambda db: admitted_batch(db, "alice", result["turnId"]))
    assert batch["conversation_id"] == team["mainConversationId"]
    assert batch["delegation"]["source_message_id"] == source["messageId"]
    assert batch["dailySlot"] == first["dailySlot"]
    assert evidence(batch)["dailySlot"] == first["dailySlot"]
    assert not batch.get("initialGoal")
    assert not await runtime.db.call(
        lambda db: row(
            db, "SELECT id FROM messages WHERE turn_id=? AND role='user'", (result["turnId"],)
        )
    )
    job = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?", (result["turnId"],)
        )
    )
    active = await runtime.mailbox.claim(job)
    assert await runtime.db.call(
        lambda db: record_retrieval(db, active, evidence(batch)),
        write=True,
    ) == evidence(batch)
    counts = await runtime.db.call(
        lambda db: [
            db.execute("SELECT count(*) FROM " + name).fetchone()[0]
            for name in [
                "conversations",
                "swarm_members",
                "swarm_goal_delegations",
                "swarm_coordination_batches",
            ]
        ]
    )
    assert counts == [1, 3, 1, 1]


async def test_dst_repeated_hour_keeps_same_slot_and_next_day_has_distinct_identity(delegated_team):
    runtime, service, team, _, _, binding, spec = delegated_team
    goal = await service.enable("alice", team["id"], spec, binding=binding)
    zone = ZoneInfo("America/New_York")
    first = await tick(
        runtime,
        team,
        goal,
        timezone=zone.key,
        clock=datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0),
    )
    repeat = await tick(
        runtime,
        team,
        goal,
        timezone=zone.key,
        clock=datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1),
    )
    tomorrow = await tick(
        runtime, team, goal, timezone=zone.key, clock=datetime(2026, 11, 2, 1, 30, tzinfo=zone)
    )
    assert first == repeat
    assert tomorrow["jobId"] != first["jobId"]


@pytest.mark.parametrize("change", ["stop", "revoke", "forget", "archive"])
async def test_queued_date_slot_does_not_outlive_original_authority(delegated_team, change):
    runtime, service, team, _, _turn, binding, spec = delegated_team
    goal = await service.enable("alice", team["id"], spec, binding=binding)
    queued = await tick(runtime, team, goal)
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
                "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'forgotten',1)",
                (goal["sourceMessageId"],),
            ),
            write=True,
        )
    else:
        await runtime.swarms.control(
            "alice",
            team["id"],
            {"commandKey": "archive", "expectedRevision": 2, "action": "archive"},
        )
    assert (await step(runtime, queued))["skipped"]
    assert not await runtime.db.call(
        lambda db: row(db, "SELECT id FROM swarm_coordination_batches")
    )


async def test_pause_preserves_daily_job_and_original_slot_until_resume(delegated_team):
    runtime, service, team, _, turn, binding, spec = delegated_team
    goal = await service.enable("alice", team["id"], spec, binding=binding)
    paused = await runtime.swarms.control(
        "alice", team["id"], {"commandKey": "pause", "expectedRevision": 2, "action": "pause"}
    )
    queued = await tick(runtime, team, goal)
    await finish(runtime, turn)
    assert (await step(runtime, queued))["waiting"] == "SWARM_COORDINATION_PAUSED"
    assert await tick(runtime, team, goal) == queued
    await runtime.swarms.control(
        "alice",
        team["id"],
        {"commandKey": "resume", "expectedRevision": paused["revision"], "action": "resume"},
    )
    assert (await step(runtime, queued))["batchId"]


@pytest.mark.parametrize(
    "kwargs", [{"slot": "x;y"}, {"timezone": "bad/zone"}, {"clock": datetime(2026, 11, 8)}]
)
async def test_invalid_date_slot_does_not_create_notification(delegated_team, kwargs):
    runtime, service, team, _, _, binding, spec = delegated_team
    goal = await service.enable("alice", team["id"], spec, binding=binding)
    with pytest.raises(DomainError):
        await tick(runtime, team, goal, **kwargs)
    assert not await runtime.db.call(
        lambda db: row(db, "SELECT id FROM jobs WHERE kind='swarm.goal.daily'")
    )


async def test_real_scheduler_consumes_daily_notification_without_worker_or_new_user(
    delegated_team,
):
    runtime, service, team, _, turn, binding, spec = delegated_team
    goal = await service.enable("alice", team["id"], spec, binding=binding)
    queued = await tick(runtime, team, goal, clock=datetime.now(ZoneInfo("Asia/Shanghai")))
    await finish(runtime, turn)
    runtime.settings.workers = 0
    await runtime.start()

    def completed(db):
        return row(
            db,
            "SELECT t.* FROM jobs n JOIN turns t ON t.id=json_extract(n.payload_json,'$.turnId') "
            "WHERE n.id=? AND n.state='done' AND t.state='completed'",
            (queued["jobId"],),
        )

    await until(runtime.db, completed)
    actual = await runtime.db.call(completed)
    assert actual["conversation_id"] == team["mainConversationId"]
    assert actual["trigger_kind"] == "continuation"
    assert not await runtime.db.call(
        lambda db: row(
            db, "SELECT id FROM messages WHERE role='user' AND turn_id=?", (actual["id"],)
        )
    )


async def test_deferred_slot_does_not_backfill_previous_date(delegated_team):
    runtime, service, team, _, turn, binding, spec = delegated_team
    goal = await service.enable("alice", team["id"], spec, binding=binding)
    queued = await tick(runtime, team, goal)
    await finish(runtime, turn)
    result = await runtime.db.call(
        lambda db: advance(db, queued["jobId"], clock=DAY + timedelta(days=1)),
        write=True,
    )
    assert result["skipped"] == "date_slot_expired"
    assert not await runtime.db.call(
        lambda db: row(db, "SELECT id FROM swarm_coordination_batches")
    )


async def test_batch_write_failure_rolls_back_before_same_notification_retry(
    delegated_team, monkeypatch
):
    runtime, service, team, _, turn, binding, spec = delegated_team
    goal = await service.enable("alice", team["id"], spec, binding=binding)
    queued = await tick(runtime, team, goal)
    await finish(runtime, turn)
    from roami_agent.storage.swarm_coordination import enqueue

    def fail(db, *args, **kwargs):
        enqueue(db, *args, **kwargs)
        raise RuntimeError("TEST_ROLLBACK")

    with monkeypatch.context() as patch:
        patch.setattr("roami_agent.storage.swarm_daily_goal.enqueue", fail)
        with pytest.raises(RuntimeError, match="TEST_ROLLBACK"):
            await step(runtime, queued)
    assert not await runtime.db.call(
        lambda db: row(db, "SELECT id FROM swarm_coordination_batches")
    )
    assert (await step(runtime, queued))["batchId"]


async def test_queued_main_turn_cannot_start_after_its_local_date(delegated_team, monkeypatch):
    runtime, service, team, _, turn, binding, spec = delegated_team
    goal = await service.enable("alice", team["id"], spec, binding=binding)
    queued = await tick(runtime, team, goal)
    await finish(runtime, turn)
    result = await step(runtime, queued)
    job = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?", (result["turnId"],)
        )
    )

    class Tomorrow(datetime):
        @classmethod
        def now(cls, tz=None):
            return (DAY + timedelta(days=1)).astimezone(tz)

    monkeypatch.setattr("roami_agent.storage.swarm_coordination_admission.datetime", Tomorrow)
    assert await runtime.mailbox.claim(job) is None
    actual = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM turns WHERE id=?", (result["turnId"],))
    )
    assert actual["state"] == "interrupted" and actual["lease_epoch"] == 0
