"""No expired, cancelled or uncertain controller can admit another input action."""

import asyncio

import pytest

from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.resource_leases import ResourceLeases
from roami_agent.dispatch.tasks import Tasks
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row


async def controller(store, owner="alice", key="first"):
    conversations = Conversations(store)
    conversation = await conversations.create(owner)
    task = await Tasks(store, conversations).create(
        owner, conversation["id"], "Browser fixture", key=key, record_intent=True
    )

    def running(db):
        db.execute("UPDATE tasks SET state='running' WHERE id=?", (task["id"],))
        db.execute("UPDATE task_attempts SET state='running' WHERE task_id=?", (task["id"],))
        return row(db, "SELECT id FROM task_attempts WHERE task_id=?", (task["id"],))["id"]

    run = await store.call(running, write=True)
    return task["id"], run


async def setup(store):
    task, run = await controller(store)
    leases = ResourceLeases(store)
    lease = await leases.claim("alice", task, run, "browser", "fixture:target")
    observation = await leases.observe(
        "alice", lease["id"], task, run, lease["lease_epoch"], "a" * 64, {"title": "Fixture"}
    )
    return leases, lease, observation, task, run


async def begin(leases, lease, observation, task, run, key="call"):
    return await leases.begin(
        "alice",
        lease["id"],
        task,
        run,
        lease["lease_epoch"],
        observation["id"],
        observation["sceneEpoch"],
        {"kind": "click"},
        key,
    )


async def test_two_tasks_cannot_claim_the_same_resource_even_after_expiry(store):
    first, second = await controller(store), await controller(store, key="second")
    leases = ResourceLeases(store)
    results = await asyncio.gather(
        *[
            leases.claim("alice", task, run, "desktop", "fixture:desktop")
            for task, run in [first, second]
        ],
        return_exceptions=True,
    )
    lease = next(item for item in results if isinstance(item, dict))
    assert sum(isinstance(item, DomainError) for item in results) == 1
    loser = second if lease["owner_task_id"] == first[0] else first
    await store.call(lambda db: db.execute("UPDATE resources SET lease_until_ms=1"), write=True)
    with pytest.raises(DomainError, match="RESOURCE_BUSY"):
        await leases.claim("alice", *loser, "desktop", "fixture:desktop")


async def test_action_receipt_prevents_replay_and_requires_fresh_observation(store):
    leases, lease, observed, task, run = await setup(store)
    action = await begin(leases, lease, observed, task, run)
    assert action["dispatch"]
    assert not (await begin(leases, lease, observed, task, run))["dispatch"]
    with pytest.raises(DomainError, match="RESOURCE_ACTION_PENDING"):
        await begin(leases, lease, observed, task, run, "second")
    await leases.finish("alice", action["id"], "succeeded", {"changed": True})
    assert not (await begin(leases, lease, observed, task, run))["dispatch"]
    with pytest.raises(DomainError, match="RESOURCE_SCENE_CHANGED"):
        await begin(leases, lease, observed, task, run, "third")
    with pytest.raises(DomainError, match="RESOURCE_ACTION_CONFLICT"):
        await leases.finish("alice", action["id"], "failed", {})


async def test_takeover_blocks_inputs_until_action_finishes_and_control_releases(store):
    leases, lease, observed, task, run = await setup(store)
    action = await begin(leases, lease, observed, task, run)
    assert (await leases.pause("alice", lease["id"]))["state"] == "pausing"
    with pytest.raises(DomainError, match="RESOURCE_INPUT_PAUSED"):
        await begin(leases, lease, observed, task, run, "after-pause")
    with pytest.raises(DomainError, match="RESOURCE_STOP_UNCONFIRMED"):
        await leases.release("alice", lease["id"], task, run, lease["lease_epoch"])
    await leases.finish("alice", action["id"], "succeeded", {"stopped": True})
    with pytest.raises(DomainError, match="RESOURCE_STOP_UNCONFIRMED"):
        await leases.resume("alice", lease["id"])
    assert (await leases.release("alice", lease["id"], task, run, lease["lease_epoch"]))[
        "state"
    ] == "paused"
    await leases.resume("alice", lease["id"])
    newer = await leases.claim("alice", task, run, "browser", "fixture:target")
    assert newer["lease_epoch"] > lease["lease_epoch"]
    with pytest.raises(DomainError, match="RESOURCE_LEASE_STALE"):
        await begin(leases, lease, observed, task, run, "old-holder")


async def test_restart_quarantines_running_action_until_real_terminal_receipt(store):
    leases, lease, observed, task, run = await setup(store)
    action = await begin(leases, lease, observed, task, run)
    recovered = ResourceLeases(store)
    await recovered.recover()
    with pytest.raises(DomainError, match="RESOURCE_INPUT_PAUSED"):
        await begin(recovered, lease, observed, task, run, "late-input")
    with pytest.raises(DomainError, match="RESOURCE_STOP_UNCONFIRMED"):
        await recovered.release("alice", lease["id"], task, run, lease["lease_epoch"])
    assert not (await begin(recovered, lease, observed, task, run))["dispatch"]
    await recovered.finish("alice", action["id"], "failed", {"receipt": "actual driver stopped"})
    assert (await recovered.release("alice", lease["id"], task, run, lease["lease_epoch"]))[
        "state"
    ] == "idle"


async def test_expired_or_cancelled_task_and_wrong_owner_cannot_act(store):
    leases, lease, observed, task, run = await setup(store)
    with pytest.raises(DomainError, match="RESOURCE_NOT_FOUND"):
        await leases.pause("bob", lease["id"])
    await store.call(lambda db: db.execute("UPDATE resources SET lease_until_ms=1"), write=True)
    with pytest.raises(DomainError, match="RESOURCE_LEASE_EXPIRED"):
        await begin(leases, lease, observed, task, run)
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='cancelling' WHERE id=?", (task,)), write=True
    )
    with pytest.raises(DomainError, match="RESOURCE_TASK_INACTIVE"):
        await leases.claim("alice", task, run, "browser", "fixture:other")


async def test_replaced_attempt_and_invalid_observation_cannot_admit_input(store):
    leases, lease, observed, task, run = await setup(store)
    with pytest.raises(DomainError, match="INVALID_RESOURCE_OBSERVATION"):
        await leases.observe(
            "alice", lease["id"], task, run, lease["lease_epoch"], "b" * 64, {"scale": float("nan")}
        )
    with pytest.raises(DomainError, match="RESOURCE_ACTION_CONFLICT"):
        await begin(leases, lease, observed, task, run)
        await leases.begin(
            "alice",
            lease["id"],
            task,
            run,
            lease["lease_epoch"],
            observed["id"],
            observed["sceneEpoch"],
            {"kind": "fill"},
            "call",
        )
    await store.call(
        lambda db: db.execute(
            "INSERT INTO task_attempts(id,task_id,task_revision,attempt_no,executor_kind,launch_id,state,native_branch_id,lease_epoch) "
            "SELECT 'new-run',task_id,task_revision,attempt_no+1,executor_kind,'new-launch','running',native_branch_id,lease_epoch+1 FROM task_attempts WHERE id=?",
            (run,),
        ),
        write=True,
    )
    with pytest.raises(DomainError, match="RESOURCE_TASK_NOT_FOUND"):
        await begin(leases, lease, observed, task, run, "obsolete-attempt")


async def test_same_unknown_receipt_is_idempotent_and_resume_does_not_restore_old_observation(
    store,
):
    leases, lease, observed, task, run = await setup(store)
    action = await begin(leases, lease, observed, task, run)
    await leases.finish("alice", action["id"], "unknown", {"error": "lost-reply"})
    before = await store.call(
        lambda db: row(db, "SELECT * FROM resources WHERE id=?", (lease["id"],))
    )
    await leases.finish("alice", action["id"], "unknown", {"error": "lost-reply"})
    after = await store.call(
        lambda db: row(db, "SELECT * FROM resources WHERE id=?", (lease["id"],))
    )
    assert before == after
    with pytest.raises(DomainError, match="RESOURCE_STOP_UNCONFIRMED"):
        await leases.resume("alice", lease["id"])
