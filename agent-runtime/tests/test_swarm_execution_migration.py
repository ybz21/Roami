"""Executor changes retire tasks rather than relabeling their native history."""

import json

import pytest
from test_swarm_members import assigned, register

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row

pytest_plugins = ["test_swarm_members"]


async def pause(runtime, group, revision):
    result = await runtime.swarms.control(
        "alice",
        group["id"],
        {"commandKey": "pause", "expectedRevision": revision, "action": "pause"},
    )

    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE turns SET state='completed' WHERE conversation_id=?",
            (group["mainConversationId"],),
        ),
        write=True,
    )
    return result


def request(member, revision, **updates):
    return {
        "commandKey": "migrate",
        "expectedRevision": revision,
        "members": [{"memberId": member["id"], "executor": "claude", "model": "free", **updates}],
    }


async def test_unassigned_role_keeps_original_identity_and_native_history(team):
    runtime, group = team
    registered = await register(runtime, group)
    member = registered["members"][0]
    old_instance = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM swarm_member_instances WHERE member_id=?", (member["id"],)
        )
    )
    await pause(runtime, group, 2)
    spec = request(member, 3)
    migrated = await runtime.swarms.migrate_execution("alice", group["id"], spec)
    assert migrated["paused"] is True
    assert await runtime.swarms.migrate_execution("alice", group["id"], spec) == migrated
    current = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM swarm_members WHERE id=?", (member["id"],))
    )
    assert current["executor"] == "claude" and current["model"] == "free"
    assert current["name"] == member["name"] and current["duty"] == member["duty"]
    assert (
        await runtime.db.call(
            lambda db: row(
                db, "SELECT * FROM swarm_member_instances WHERE member_id=?", (member["id"],)
            )
        )
        == old_instance
    )
    assert (await runtime.db.call(lambda db: row(db, "SELECT count(*) AS n FROM tasks")))["n"] == 0
    snapshot = await runtime.swarms.snapshot("alice", group["id"])
    assert snapshot["members"][0]["instance"] is None


async def test_pause_and_revision_are_required_and_failure_is_atomic(team):
    runtime, group = team
    member = (await register(runtime, group))["members"][0]
    with pytest.raises(DomainError, match="SWARM_MIGRATION_REQUIRES_PAUSE"):
        await runtime.swarms.migrate_execution("alice", group["id"], request(member, 2))
    await pause(runtime, group, 2)
    with pytest.raises(DomainError, match="SWARM_PLAN_CHANGED"):
        await runtime.swarms.migrate_execution("alice", group["id"], request(member, 2))
    spec = request(member, 3)
    spec["members"].append({"memberId": "foreign", "executor": "claude", "model": "free"})
    with pytest.raises(DomainError, match="SWARM_MEMBER_NOT_FOUND"):
        await runtime.swarms.migrate_execution("alice", group["id"], spec)
    assert (
        await runtime.db.call(
            lambda db: row(db, "SELECT executor FROM swarm_members WHERE id=?", (member["id"],))
        )
    )["executor"] == "native"


@pytest.mark.parametrize("state", ["queued", "running", "cancelling", "waiting_user"])
async def test_active_or_unresolved_tasks_cannot_be_replaced(team, state):
    runtime, group = team
    member, work = await assigned(runtime, group)
    await runtime.db.call(
        lambda db: db.execute("UPDATE tasks SET state=? WHERE id=?", (state, work["task_id"])),
        write=True,
    )
    await pause(runtime, group, 3)
    with pytest.raises(DomainError, match="SWARM_MEMBER_STOP_REQUIRED"):
        await runtime.swarms.migrate_execution("alice", group["id"], request(member, 4))


async def test_missing_stop_proof_is_not_task_completion(team):
    runtime, group = team
    member, work = await assigned(runtime, group)
    await runtime.db.call(
        lambda db: db.execute("UPDATE tasks SET state='failed' WHERE id=?", (work["task_id"],)),
        write=True,
    )
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE jobs SET state='failed' WHERE aggregate_id=?", (work["task_id"],)
        ),
        write=True,
    )
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE task_attempts SET state='unknown' WHERE task_id=?", (work["task_id"],)
        ),
        write=True,
    )
    await pause(runtime, group, 3)
    with pytest.raises(DomainError, match="SWARM_MEMBER_STOP_UNCONFIRMED"):
        await runtime.swarms.migrate_execution("alice", group["id"], request(member, 4))


async def test_stopped_generation_is_retained_and_next_assignment_keeps_model(team):
    runtime, group = team
    member, work = await assigned(runtime, group)
    task_id = work["task_id"]

    def finished(db):
        db.execute("UPDATE tasks SET state='cancelled' WHERE id=?", (task_id,))
        db.execute("UPDATE jobs SET state='done' WHERE aggregate_id=?", (task_id,))
        db.execute(
            "UPDATE task_attempts SET state='cancelled',result_json=? WHERE task_id=?",
            (
                json.dumps({"state": "cancelled", "inputStopped": True, "outcomeKnown": True}),
                task_id,
            ),
        )

    await runtime.db.call(finished, write=True)
    before = await runtime.db.call(lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (task_id,)))
    await pause(runtime, group, 3)
    await runtime.swarms.migrate_execution("alice", group["id"], request(member, 4))
    assert (
        await runtime.db.call(lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (task_id,)))
        == before
    )
    retired = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM swarm_work_items WHERE id=?", (work["id"],))
    )
    assert (
        retired["task_id"] is None and retired["dispatch_error"] == "SWARM_MEMBER_REASSIGN_REQUIRED"
    )
    await runtime.swarms.plan(
        "alice",
        group["id"],
        {
            "commandKey": "reassign",
            "expectedRevision": 5,
            "items": [
                {
                    "memberId": member["id"],
                    "member": member["name"],
                    "executor": "claude",
                    "title": "Read again",
                    "goal": "New bounded assignment",
                    "acceptance": "Verify references",
                }
            ],
        },
    )
    next_work = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM swarm_work_items WHERE id=?", (work["id"],))
    )
    assert next_work["model"] == "free" and next_work["dispatch_error"] is None
    assert (await runtime.swarms.snapshot("alice", group["id"]))["paused"] is True
    assert (await runtime.db.call(lambda db: row(db, "SELECT count(*) AS n FROM tasks")))["n"] == 1

    await runtime.swarms.control(
        "alice", group["id"], {"commandKey": "resume", "expectedRevision": 6, "action": "resume"}
    )
    await runtime.swarms.advance({"id": "new-generation", "aggregate_id": group["id"]})
    newest = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM swarm_work_items WHERE id=?", (work["id"],))
    )
    assert newest["task_id"] and newest["task_id"] != task_id
    new_task = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (newest["task_id"],))
    )
    assert json.loads(new_task["intent_json"])["executor"] == "claude"
    assert json.loads(new_task["intent_json"])["model"] == "free"
    assert (
        await runtime.db.call(lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (task_id,)))
        == before
    )
    await runtime.swarms.advance({"id": "repeat", "aggregate_id": group["id"]})
    assert (await runtime.db.call(lambda db: row(db, "SELECT count(*) AS n FROM tasks")))["n"] == 2
