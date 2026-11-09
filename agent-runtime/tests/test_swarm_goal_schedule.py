"""An explicit wait reuses real Main scope and does not hide unfinished work."""

import json
from copy import deepcopy

import pytest
from test_swarm_coordination_policy import coordinated_tools as coordinated_tools_fixture
from test_swarm_coordination_policy import coordination as coordination_fixture
from test_swarm_coordination_policy import delegated_team as delegated_team_fixture
from test_swarm_coordination_policy import invoke
from test_swarm_goal_continuation import idle_delivery as idle_delivery_fixture
from test_swarm_goal_continuation import reply
from test_swarm_goal_continuity import delivery as delivery_fixture

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.storage.database import row
from roami_agent.storage.swarm_goal_checkpoint import checkpoint_context, validate_final_checkpoint

coordination = coordination_fixture
delegated_team = delegated_team_fixture
coordinated_tools = coordinated_tools_fixture
delivery = delivery_fixture
idle_delivery = idle_delivery_fixture


@pytest.fixture
async def wait_case(idle_delivery, monkeypatch):
    runtime, binding, actor = idle_delivery
    value = await runtime.db.call(lambda db: checkpoint_context(db, binding))
    proof = {
        "kind": "registered_goal_schedule",
        "projectId": "project-a",
        "mainConversationId": binding["conversation"],
        "swarmId": value["swarm_id"],
        "delegationId": value["delegation_id"],
        "jobName": "morning",
        "nextDueMs": now_ms() + 3600000,
        "observedAtMs": now_ms(),
        "nextTickMs": now_ms() + 60000,
        "commandSha256": "a" * 64,
    }
    calls = []

    async def source(scope):
        calls.append(scope)
        return deepcopy(proof)

    service = runtime.tools.registry["swarm_goal_wait"].handler.__self__
    monkeypatch.setattr(service.source, "read", source)
    return runtime, binding, actor, value, proof, calls


async def acknowledge(case):
    runtime, binding, _, value, _, _ = case
    for item in value["inputs"]:
        await invoke(
            runtime,
            binding,
            "swarm_post",
            {
                "swarmId": value["swarm_id"],
                "kind": "reply",
                "replyTo": item["postId"],
                "messageKey": "settled-" + str(item["postId"]),
                "text": "当前交付已处理，保留原事实。",
            },
        )


async def wait(case, **changes):
    runtime, binding, _, value, _, _ = case
    return await invoke(
        runtime,
        binding,
        "bash",
        {
            "argv": [
                "roami",
                "swarm",
                "goal",
                "wait",
                "--input",
                json.dumps(
                    {
                        "swarmId": value["swarm_id"],
                        "reason": "今日工作已收口，等原计划继续。",
                        **changes,
                    }
                ),
            ]
        },
    )


async def test_explicit_wait_allows_actual_main_reply_without_new_jobs_or_instances(wait_case):
    runtime, binding, _, _, _, calls = wait_case
    await acknowledge(wait_case)
    before = await runtime.db.call(
        lambda db: {
            name: db.execute("SELECT count(*) FROM " + name).fetchone()[0]
            for name in ["jobs", "tasks", "task_attempts", "swarm_members"]
        }
    )
    with pytest.raises(DomainError, match="SWARM_GOAL_NEXT_STEP_REQUIRED"):
        await reply(runtime, binding)
    first = await wait(wait_case)
    assert first["kind"] == "scheduled_goal_wait" and first["goalComplete"] is False
    assert await wait(wait_case) == first
    assert "reply" in await reply(runtime, binding)
    after = await runtime.db.call(
        lambda db: {
            name: db.execute("SELECT count(*) FROM " + name).fetchone()[0] for name in before
        }
    )
    assert before == after and len(calls) >= 3
    recorded = await runtime.db.call(
        lambda db: row(
            db, "SELECT receipt_json FROM swarm_commands WHERE command_key LIKE 'goal-checkpoint:%'"
        )
    )
    assert (
        json.loads(recorded["receipt_json"])["decision"]["kind"]
        == "waiting_for_registered_schedule"
    )


async def test_unanswered_current_handoff_cannot_be_hidden_by_a_future_schedule(wait_case):
    _, _, _, _, _, calls = wait_case
    with pytest.raises(DomainError, match="SWARM_GOAL_WORK_UNSETTLED"):
        await wait(wait_case)
    assert not calls


@pytest.mark.parametrize(
    "state,run_state",
    [
        ("waiting_user", "succeeded"),
        ("failed", "succeeded"),
        ("succeeded", "unknown"),
        ("running", "running"),
    ],
)
async def test_unfinished_or_unknown_original_work_refuses_schedule_wait(
    wait_case, state, run_state
):
    runtime, _, actor, _, _, calls = wait_case
    await acknowledge(wait_case)

    def change(db):
        db.execute("UPDATE tasks SET state=? WHERE id=?", (state, actor["taskId"]))
        db.execute("UPDATE task_attempts SET state=? WHERE id=?", (run_state, actor["runId"]))

    await runtime.db.call(change, write=True)
    with pytest.raises(DomainError, match="SWARM_GOAL_WORK_UNSETTLED"):
        await wait(wait_case)
    assert not calls


async def test_wait_is_rechecked_after_live_probe_and_before_final_reply(wait_case):
    runtime, binding, _, _, proof, _ = wait_case
    await acknowledge(wait_case)
    await wait(wait_case)
    proof["commandSha256"] = "b" * 64
    with pytest.raises(DomainError, match="GOAL_SCHEDULE_CHANGED"):
        await reply(runtime, binding)


async def test_different_reason_cannot_replace_an_immutable_wait(wait_case):
    await acknowledge(wait_case)
    await wait(wait_case)
    with pytest.raises(DomainError, match="SWARM_GOAL_CHECKPOINT_CHANGED"):
        await wait(wait_case, reason="换一个决定")


async def test_elapsed_wait_does_not_pass_final_storage_gate(wait_case, monkeypatch):
    runtime, binding, _, _, proof, _ = wait_case
    await acknowledge(wait_case)
    await wait(wait_case)
    await reply(runtime, binding)
    monkeypatch.setattr(
        "roami_agent.storage.swarm_goal_schedule.now_ms", lambda: proof["nextDueMs"] + 1
    )
    turn = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?",
            (binding["turnId"],),
        )
    )
    with pytest.raises(DomainError, match="GOAL_SCHEDULE_NOT_FUTURE"):
        await runtime.db.call(lambda db: validate_final_checkpoint(db, turn))


@pytest.mark.parametrize("fault", ["swarm", "owner", "conversation", "lease", "worker"])
async def test_other_scope_cannot_record_a_wait(wait_case, fault):
    runtime, binding, actor, value, _, calls = wait_case
    await acknowledge(wait_case)
    changes = {
        "owner": {"owner": "bob"},
        "conversation": {"conversation": "Home"},
        "lease": {"leaseEpoch": -1},
        "worker": {"taskId": actor["taskId"]},
        "swarm": {},
    }
    with pytest.raises(DomainError):
        await invoke(
            runtime,
            {**binding, **changes[fault]},
            "swarm_goal_wait",
            {"swarmId": "other" if fault == "swarm" else value["swarm_id"], "reason": "等排期"},
        )
    assert not calls


@pytest.mark.parametrize("fault", ["revoked", "paused", "lease", "source", "task"])
async def test_authority_changes_during_live_schedule_read_do_not_persist_wait(
    wait_case, fault, monkeypatch
):
    runtime, binding, actor, value, proof, _ = wait_case
    await acknowledge(wait_case)
    source = runtime.tools.registry["swarm_goal_wait"].handler.__self__.source

    def change(db):
        if fault == "revoked":
            db.execute(
                "UPDATE swarm_goal_delegations SET revoked_ms=1,revoked_by_message_id=? WHERE id=?",
                (binding["originMessageId"], value["delegation_id"]),
            )
        elif fault == "paused":
            db.execute("UPDATE swarm_groups SET paused=1 WHERE id=?", (value["swarm_id"],))
        elif fault == "lease":
            db.execute(
                "UPDATE turns SET lease_epoch=lease_epoch+1 WHERE id=?", (binding["turnId"],)
            )
        elif fault == "source":
            db.execute("UPDATE messages SET deleted_ms=1 WHERE id=?", (binding["originMessageId"],))
        else:
            db.execute("UPDATE tasks SET revision=revision+1 WHERE id=?", (actor["taskId"],))

    async def changed(scope):
        await runtime.db.call(change, write=True)
        return deepcopy(proof)

    monkeypatch.setattr(source, "read", changed)
    with pytest.raises(DomainError):
        await wait(wait_case)
    assert (
        await runtime.db.call(
            lambda db: db.execute(
                "SELECT count(*) FROM swarm_commands WHERE command_key LIKE 'goal-scheduled-wait:%'"
            ).fetchone()[0]
        )
        == 0
    )


async def test_model_cannot_supply_a_local_schedule_receipt_or_future_time(wait_case):
    _, _, _, _, _, calls = wait_case
    await acknowledge(wait_case)
    with pytest.raises(DomainError):
        await wait(wait_case, nextDueMs=9999999999999, schedule={"enabled": True})
    assert not calls
