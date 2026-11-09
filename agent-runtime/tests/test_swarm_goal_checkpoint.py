import json

import pytest
from test_swarm_coordination_policy import coordinated_tools as coordinated_tools_fixture
from test_swarm_coordination_policy import coordination as coordination_fixture
from test_swarm_coordination_policy import delegated_team as delegated_team_fixture
from test_swarm_coordination_tasks import continuing_member as continuing_member_fixture
from test_swarm_coordination_tasks import operation, request, revoke

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.swarm_goal_checkpoint import active_next_steps

coordination = coordination_fixture
delegated_team = delegated_team_fixture
coordinated_tools = coordinated_tools_fixture
continuing_member = continuing_member_fixture


async def test_next_step_uses_current_original_run_and_cannot_be_claimed_by_a_worker(
    coordinated_tools,
):
    runtime, _, _, _, actor, binding = coordinated_tools
    main = {**binding, "role": "main"}

    def running(db):
        db.execute("UPDATE tasks SET state='running' WHERE id=?", (actor["taskId"],))
        db.execute(
            "UPDATE task_attempts SET state='running',finished_ms=NULL WHERE id=?",
            (actor["runId"],),
        )

    await runtime.db.call(running, write=True)
    proof = await runtime.db.call(lambda db: active_next_steps(db, main))
    assert any(
        step["kind"] == "running_original_task"
        and step["taskId"] == actor["taskId"]
        and step["runId"] == actor["runId"]
        for step in proof["steps"]
    )
    with pytest.raises(DomainError, match="SWARM_COORDINATION_SCOPE_CONFLICT"):
        await runtime.db.call(lambda db: active_next_steps(db, {**main, "role": "worker"}))


@pytest.mark.parametrize(
    "task_state,attempt_state",
    [
        ("succeeded", "succeeded"),
        ("failed", "failed"),
        ("waiting_user", "unknown"),
        ("waiting_user", "succeeded"),
    ],
)
async def test_completed_or_unknown_execution_is_not_a_future_step(
    coordinated_tools, task_state, attempt_state
):
    runtime, _, _, _, actor, binding = coordinated_tools

    def change(db):
        db.execute("UPDATE tasks SET state=? WHERE id=?", (task_state, actor["taskId"]))
        db.execute("UPDATE task_attempts SET state=? WHERE id=?", (attempt_state, actor["runId"]))

    await runtime.db.call(change, write=True)
    proof = await runtime.db.call(lambda db: active_next_steps(db, {**binding, "role": "main"}))
    assert not any(item["taskId"] == actor["taskId"] for item in proof["steps"])


@pytest.mark.parametrize("fault", [None, "revision", "run", "delegation", "done"])
async def test_actual_continuation_receipt_is_fenced_by_current_identity(continuing_member, fault):
    runtime, _, _, _, binding, _, _ = continuing_member
    receipt = await request(continuing_member)
    pending = await operation(runtime, receipt)
    payload = json.loads(pending["payload_json"])
    if fault == "revision":
        payload["expectedRevision"] += 1
    elif fault == "run":
        payload["coordinationAuthorization"]["sourceRunId"] = "old-run"
    elif fault == "delegation":
        payload["coordinationAuthorization"]["delegationId"] = "other-goal"
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE jobs SET payload_json=?,state=? WHERE id=?",
            (json.dumps(payload), "done" if fault == "done" else pending["state"], pending["id"]),
        ),
        write=True,
    )
    proof = await runtime.db.call(lambda db: active_next_steps(db, {**binding, "role": "main"}))
    assert any(
        step.get("jobId") == pending["id"] and step["kind"] == "pending_continuation"
        for step in proof["steps"]
    ) is (fault is None)


async def test_revoked_goal_cannot_keep_a_pending_step_alive(continuing_member):
    runtime, _, _, _, binding, _, _ = continuing_member
    await request(continuing_member)
    await revoke(continuing_member)
    with pytest.raises(DomainError):
        await runtime.db.call(lambda db: active_next_steps(db, {**binding, "role": "main"}))


async def test_forgotten_task_source_cannot_be_waiting_evidence(continuing_member):
    runtime, _, _, actor, binding, _, _ = continuing_member
    await request(continuing_member)
    await runtime.db.call(
        lambda db: db.execute(
            "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) "
            "SELECT owner_id,origin_message_id,'forgotten',1 FROM tasks WHERE id=?",
            (actor["taskId"],),
        ),
        write=True,
    )
    try:
        proof = await runtime.db.call(lambda db: active_next_steps(db, {**binding, "role": "main"}))
    except DomainError:
        return
    assert not any(item["taskId"] == actor["taskId"] for item in proof["steps"])


@pytest.mark.parametrize("stale", [False, True])
async def test_waiting_for_admission_requires_current_execution_job(coordinated_tools, stale):
    runtime, _, _, _, actor, binding = coordinated_tools

    def queued(db):
        db.execute("UPDATE tasks SET state='queued' WHERE id=?", (actor["taskId"],))
        db.execute(
            "UPDATE task_attempts SET state='accepted',finished_ms=NULL WHERE id=?",
            (actor["runId"],),
        )
        result = db.execute(
            "UPDATE jobs SET state='queued',payload_json=json_set(payload_json,'$.runId',?) "
            "WHERE kind='task.run' AND aggregate_id=?",
            ("old-run" if stale else actor["runId"], actor["taskId"]),
        )
        assert result.rowcount > 0

    await runtime.db.call(queued, write=True)
    proof = await runtime.db.call(lambda db: active_next_steps(db, {**binding, "role": "main"}))
    assert (
        any(
            item["kind"] == "pending_original_execution" and item["runId"] == actor["runId"]
            for item in proof["steps"]
        )
        is not stale
    )


async def test_finished_attempt_cannot_look_like_live_work(coordinated_tools):
    runtime, _, _, _, actor, binding = coordinated_tools
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE task_attempts SET finished_ms=1 WHERE id=?", (actor["runId"],)
        ),
        write=True,
    )
    proof = await runtime.db.call(lambda db: active_next_steps(db, {**binding, "role": "main"}))
    assert not any(item["taskId"] == actor["taskId"] for item in proof["steps"])


async def test_all_original_members_finished_exposes_the_production_gap(coordinated_tools):
    runtime, _, _, _, _, binding = coordinated_tools

    def finished(db):
        db.execute(
            "UPDATE task_attempts SET state='succeeded',finished_ms=1 "
            "WHERE task_id IN (SELECT id FROM tasks WHERE origin_conversation_id=?)",
            (binding["conversation"],),
        )
        db.execute(
            "UPDATE tasks SET state='succeeded' WHERE origin_conversation_id=?",
            (binding["conversation"],),
        )

    await runtime.db.call(finished, write=True)
    proof = await runtime.db.call(lambda db: active_next_steps(db, {**binding, "role": "main"}))
    assert proof["steps"] == []
