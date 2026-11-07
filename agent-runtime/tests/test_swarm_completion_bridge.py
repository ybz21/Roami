"""Original execution results wake only their scoped Main, once per actual fact."""

import asyncio
import json
import sqlite3

import pytest
from test_swarm_coordination import claim, queue
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture
from test_swarm_delegations import finish
from test_swarm_result_observations import build, status

from roami_agent.protocol.identity import identity
from roami_agent.storage.database import row, rows
from roami_agent.storage.swarm_completion_bridge import KIND, advance, route

coordination = coordination_fixture
delegated_team = delegated_team_fixture


async def completed(runtime, actor):
    result = {
        "state": "succeeded",
        "summary": "Actual original-run evidence",
        "inputStopped": True,
        "outcomeKnown": True,
    }
    await runtime.tasks.report("alice", actor["taskId"], actor["runId"], 1, result)
    task, run = await runtime.db.call(
        lambda db: (
            row(db, "SELECT * FROM tasks WHERE id=?", (actor["taskId"],)),
            row(db, "SELECT * FROM task_attempts WHERE id=?", (actor["runId"],)),
        )
    )
    await runtime.dispatch.complete(task, run, result, "waiting_user")
    job = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT * FROM jobs WHERE kind=? AND aggregate_id=? ORDER BY rowid DESC LIMIT 1",
            (KIND, actor["taskId"]),
        )
    )
    return task, run, result, job


async def counts(runtime):
    return await runtime.db.call(
        lambda db: {
            name: db.execute("SELECT count(*) FROM " + name).fetchone()[0]
            for name in [
                "conversations",
                "turns",
                "swarm_coordination_batches",
                "swarm_result_observations",
            ]
        }
    )


async def consume(runtime, job):
    return await runtime.db.call(lambda db: advance(db, job["id"]), write=True)


async def control(runtime, team, action):
    current = await runtime.swarms.snapshot("alice", team["id"], include_memory=False)
    return await runtime.swarms.control(
        "alice",
        team["id"],
        {"commandKey": action, "expectedRevision": current["revision"], "action": action},
    )


async def test_completion_queues_one_original_main_batch_without_read_or_acceptance_claim(
    coordination,
):
    runtime, _, team, _, _, actor = coordination
    before = await counts(runtime)
    task, run, result, job = await completed(runtime, actor)
    assert job and (await counts(runtime))["turns"] == before["turns"]
    event = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT payload_json FROM events WHERE event_key=?",
            ("coordination-completion:" + job["dedupe_key"],),
        )
    )
    assert json.loads(event["payload_json"])["activity"]["state"] == "waiting_user"
    payload = json.loads(job["payload_json"])
    assert (
        payload["swarmId"] == team["id"] and payload["executionReceipt"]["runId"] == actor["runId"]
    )
    receipt = await consume(runtime, job)
    assert receipt["observed"] is False
    assert (await counts(runtime))["turns"] == before["turns"] + 1
    assert (await counts(runtime))["conversations"] == before["conversations"]
    assert not (await counts(runtime))["swarm_result_observations"]
    assert await consume(runtime, job) == receipt
    completion = {
        "state": "waiting_user",
        "result": result,
        "executionReceipt": payload["executionReceipt"],
    }
    assert await runtime.db.call(
        lambda db: route(db, task, run, completion, job["dedupe_key"]), write=True
    )
    assert (await counts(runtime))["turns"] == before["turns"] + 1
    turn = await claim(runtime, receipt)
    assert turn["conversation_id"] == team["mainConversationId"]


@pytest.mark.parametrize("block", ["pause", "user"])
async def test_busy_or_paused_main_retains_same_notification_until_available(coordination, block):
    runtime, _, team, _, _, actor = coordination
    _, _, _, job = await completed(runtime, actor)
    if block == "pause":
        await control(runtime, team, "pause")
    else:
        accepted = await runtime.conversations.accept(
            "alice", team["mainConversationId"], "actual-user", "Handle this first"
        )
    before = await counts(runtime)
    waiting = await consume(runtime, job)
    assert waiting["waiting"] == ("SWARM_COORDINATION_PAUSED" if block == "pause" else "MAIN_BUSY")
    assert await counts(runtime) == before
    if block == "pause":
        await control(runtime, team, "resume")
    else:
        await finish(runtime, await claim(runtime, {"turnId": accepted["turnId"]}))
    assert (await consume(runtime, job))["batchId"]


async def test_late_result_does_not_modify_or_hide_behind_earlier_handoff_batch(coordination):
    runtime, _, team, _, post, actor = coordination
    await post("handoff", "handoff")
    old = await queue(runtime, team)
    old_turn = await claim(runtime, old)
    frozen_before = await runtime.db.call(
        lambda db: rows(
            db, "SELECT * FROM swarm_coordination_inputs WHERE batch_id=?", (old["batchId"],)
        )
    )
    _, _, _, job = await completed(runtime, actor)
    assert (await consume(runtime, job))["waiting"] == "MAIN_BUSY"
    await finish(runtime, old_turn)
    newer = await consume(runtime, job)
    assert newer["batchId"] != old["batchId"]
    assert frozen_before == await runtime.db.call(
        lambda db: rows(
            db, "SELECT * FROM swarm_coordination_inputs WHERE batch_id=?", (old["batchId"],)
        )
    )


async def test_actual_status_observation_consumes_notification_without_another_turn(coordination):
    runtime, _, team, _, post, actor = coordination
    await post("handoff", "handoff")
    old = await queue(runtime, team)
    turn = await claim(runtime, old)
    _, _, _, job = await completed(runtime, actor)
    await status(runtime, turn, actor)
    plan, _ = await build(runtime, turn)
    await runtime.manifests.record(turn, 1, "fixture", "wire", plan, [], "main")
    await finish(runtime, turn)
    before = await counts(runtime)
    consumed = await consume(runtime, job)
    assert consumed["observedManifestId"]
    assert await counts(runtime) == before


async def test_result_already_frozen_retains_original_batch_even_before_model_read(coordination):
    runtime, _, team, _, _, actor = coordination
    _, _, _, job = await completed(runtime, actor)
    frozen = await queue(runtime, team)
    before = await counts(runtime)
    actual = await consume(runtime, job)
    assert actual["batchId"] == frozen["batchId"] and actual["observed"] is False
    assert await counts(runtime) == before


async def test_freeze_failure_rolls_back_main_and_job_then_retries_same_receipt(coordination):
    runtime, _, _, _, _, actor = coordination
    _, _, _, job = await completed(runtime, actor)
    await runtime.db.call(
        lambda db: db.execute(
            "CREATE TRIGGER fail_bridge BEFORE INSERT ON events WHEN NEW.kind='swarm.coordination.queued' BEGIN SELECT RAISE(ABORT,'bridge freeze failed'); END"
        ),
        write=True,
    )
    before = await counts(runtime)
    with pytest.raises(sqlite3.IntegrityError, match="bridge freeze failed"):
        await consume(runtime, job)
    assert await counts(runtime) == before
    assert (
        await runtime.db.call(lambda db: row(db, "SELECT state FROM jobs WHERE id=?", (job["id"],)))
    )["state"] == "queued"
    await runtime.db.call(lambda db: db.execute("DROP TRIGGER fail_bridge"), write=True)
    assert (await consume(runtime, job))["batchId"]


async def test_existing_legacy_completion_is_not_rewritten_or_retroactively_coordinated(
    coordination,
):
    runtime, _, team, _, _, actor = coordination
    turn_id, job_id = identity(), identity()

    def legacy(db):
        conversation = row(
            db,
            "SELECT active_branch_id FROM conversations WHERE id=?",
            (team["mainConversationId"],),
        )
        db.execute(
            "INSERT INTO turns(id,conversation_id,branch_id,trigger_kind,state,created_ms) VALUES(?,?,?,'completion','queued',1)",
            (turn_id, team["mainConversationId"], conversation["active_branch_id"]),
        )
        db.execute(
            "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) VALUES(?,'turn.run',?,?,'{\"completion\":{\"summary\":\"original input\"}}','queued',1)",
            (job_id, turn_id, "task.completion:" + actor["runId"] + ":waiting_user"),
        )

    await runtime.db.call(legacy, write=True)
    before = await runtime.db.call(lambda db: row(db, "SELECT * FROM jobs WHERE id=?", (job_id,)))
    _, _, _, bridge = await completed(runtime, actor)
    assert bridge is None
    assert (
        await runtime.db.call(lambda db: row(db, "SELECT * FROM jobs WHERE id=?", (job_id,)))
        == before
    )


async def test_same_state_known_result_gets_new_receipt_identity_after_unknown(coordination):
    runtime, _, _, _, _, actor = coordination
    await runtime.db.call(
        lambda db: db.execute("UPDATE tasks SET state='running' WHERE id=?", (actor["taskId"],)),
        write=True,
    )
    task, run = await runtime.db.call(
        lambda db: (
            row(db, "SELECT * FROM tasks WHERE id=?", (actor["taskId"],)),
            row(db, "SELECT * FROM task_attempts WHERE id=?", (actor["runId"],)),
        )
    )
    await runtime.dispatch.complete(
        task,
        run,
        {"state": "failed", "summary": "Unknown", "outcomeKnown": False, "inputStopped": False},
        "interrupted",
        unknown=True,
    )
    old = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind=? AND aggregate_id=?", (KIND, actor["taskId"])
        )
    )
    assert old
    await runtime.tasks.report(
        "alice",
        actor["taskId"],
        actor["runId"],
        1,
        {
            "state": "succeeded",
            "summary": "Actual reconciled result",
            "outcomeKnown": True,
            "inputStopped": True,
        },
    )
    jobs = await runtime.db.call(
        lambda db: rows(
            db,
            "SELECT * FROM jobs WHERE kind=? AND aggregate_id=? ORDER BY rowid",
            (KIND, actor["taskId"]),
        )
    )
    assert len(jobs) == 2 and jobs[0]["payload_json"] == old["payload_json"]
    assert (
        json.loads(jobs[0]["payload_json"])["executionReceipt"]["receiptId"]
        != json.loads(jobs[1]["payload_json"])["executionReceipt"]["receiptId"]
    )
    assert (await consume(runtime, jobs[0]))["skipped"] == "result_superseded"
    assert (await consume(runtime, jobs[1]))["batchId"]


@pytest.mark.parametrize("change", ["forgotten", "revision", "revoked"])
async def test_unavailable_source_or_new_revision_never_wakes_another_main(coordination, change):
    runtime, _, _team, enabled, _, actor = coordination
    _, _, _, job = await completed(runtime, actor)

    def invalidate(db):
        grant = row(
            db, "SELECT * FROM swarm_goal_delegations WHERE id=?", (enabled["delegationId"],)
        )
        if change == "forgotten":
            db.execute(
                "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'forgotten',1)",
                (grant["source_message_id"],),
            )
        elif change == "revision":
            db.execute("UPDATE tasks SET revision=2 WHERE id=?", (actor["taskId"],))
        else:
            db.execute(
                "UPDATE swarm_goal_delegations SET revoked_ms=1,revoked_by_message_id=source_message_id WHERE id=?",
                (grant["id"],),
            )

    await runtime.db.call(invalidate, write=True)
    before = await counts(runtime)
    result = await consume(runtime, job)
    assert result["skipped"] == "source_or_scope_unavailable"
    assert await counts(runtime) == before


async def test_existing_scheduler_job_handler_uses_bridge_and_preserves_queued_user_priority(
    coordination,
):
    runtime, _, team, _, _, actor = coordination
    _, _, _, job = await completed(runtime, actor)
    await runtime.conversations.accept(
        "alice", team["mainConversationId"], "first-user", "User first"
    )
    before = await counts(runtime)
    await runtime.scheduler._job(job)
    current = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM jobs WHERE id=?", (job["id"],))
    )
    assert current["state"] == "queued" and current["available_ms"] > job["available_ms"]
    assert await counts(runtime) == before


async def test_revoked_automatic_execution_never_falls_back_to_unscoped_completion(coordination):
    runtime, _, team, enabled, _, actor = coordination

    def bind(db):
        task = row(db, "SELECT * FROM tasks WHERE id=?", (actor["taskId"],))
        grant = row(
            db, "SELECT * FROM swarm_goal_delegations WHERE id=?", (enabled["delegationId"],)
        )
        member = row(
            db,
            "SELECT id FROM swarm_members WHERE current_work_id IN (SELECT id FROM swarm_work_items WHERE task_id=?)",
            (task["id"],),
        )
        intent = json.loads(task["intent_json"])
        intent["coordinationAuthorization"] = {
            "delegationId": grant["id"],
            "swarmId": team["id"],
            "memberId": member["id"],
            "taskId": task["id"],
            "projectId": "project-a",
            "sourceMessageId": grant["source_message_id"],
            "sourceSha256": grant["source_sha256"],
            "goalQuote": grant["source_quote"],
        }
        db.execute("UPDATE tasks SET intent_json=? WHERE id=?", (json.dumps(intent), task["id"]))
        db.execute(
            "UPDATE swarm_goal_delegations SET revoked_ms=1,revoked_by_message_id=source_message_id WHERE id=?",
            (grant["id"],),
        )

    await runtime.db.call(bind, write=True)
    before = await counts(runtime)
    _, _, _, job = await completed(runtime, actor)
    assert job and (await counts(runtime))["turns"] == before["turns"]
    assert (await consume(runtime, job))["skipped"] == "source_or_scope_unavailable"
    assert (await counts(runtime))["turns"] == before["turns"]


async def test_bridge_is_not_starved_by_large_memory_backlog(coordination):
    runtime, _, _, _, _, actor = coordination
    await completed(runtime, actor)

    def backlog(db):
        db.executemany(
            "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) VALUES(?,'memory.extract','fixture',?,'{}','queued',0)",
            [(identity(), "memory-fixture:" + str(i)) for i in range(120)],
        )

    await runtime.db.call(backlog, write=True)
    kinds = []

    async def capture(item):
        kinds.append(item["kind"])
        await runtime.db.call(
            lambda db: db.execute("UPDATE jobs SET state='done' WHERE id=?", (item["id"],)),
            write=True,
        )

    runtime.scheduler._job = capture
    await runtime.scheduler._scan()
    handles = [item["handle"] for item in runtime.scheduler.active.values()]
    await asyncio.gather(*handles)
    assert KIND in kinds


async def test_metadata_only_status_cannot_swallow_unread_result_notification(coordination):
    runtime, _, team, _, post, actor = coordination
    await post("handoff", "handoff")
    old = await queue(runtime, team)
    turn = await claim(runtime, old)
    _, _, _, job = await completed(runtime, actor)
    await status(runtime, turn, actor, include_result=False)
    plan, prompt = await build(runtime, turn)
    assert any(
        item.get("role") == "tool" and "executionReceipt" in str(item.get("content"))
        for item in prompt
    )
    await runtime.manifests.record(turn, 1, "fixture", "wire", plan, [], "main")
    assert (await counts(runtime))["swarm_result_observations"] == 0
    await finish(runtime, turn)
    assert (await consume(runtime, job))["batchId"] != old["batchId"]
