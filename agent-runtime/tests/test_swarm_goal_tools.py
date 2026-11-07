import json

import pytest
from test_runtime import until
from test_swarm_collaboration import advance as dispatch_plan
from test_swarm_collaboration import item
from test_swarm_command_contract import command
from test_swarm_delegations import delegated_team as delegated_team_fixture
from test_swarm_delegations import finish

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row

delegated_team = delegated_team_fixture


def actor(turn, binding):
    return {**binding, "owner": "alice", "leaseEpoch": turn["lease_epoch"], "toolCallId": "goal"}


def goal_command(action, args):
    return command(["roami", "swarm", "goal", action, "--input", json.dumps(args)])


async def prepare_roles(runtime, team):
    members = (await runtime.swarms.snapshot("alice", team["id"], include_memory=False))["members"]
    await runtime.swarms.plan(
        "alice",
        team["id"],
        {
            "commandKey": "plan",
            "expectedRevision": 2,
            "items": [item(m["name"], executor=m["executor"], memberId=m["id"]) for m in members],
        },
    )
    await dispatch_plan(runtime.swarms, team)


async def test_real_cli_entry_enables_once_and_can_read_and_revoke_its_goal(delegated_team):
    runtime, _, team, _, turn, binding, spec = delegated_team
    await prepare_roles(runtime, team)
    binding = actor(turn, binding)
    read = goal_command("status", {"swarmId": team["id"]})
    assert (await runtime.tools.invoke(read, "main", binding))["revision"] == 0
    args = {"swarmId": team["id"], **{k: v for k, v in spec.items() if k != "commandKey"}}
    call = goal_command("enable", args)
    first = await runtime.tools.invoke(call, "main", binding)
    second = await runtime.tools.invoke(call, "main", {**binding, "toolCallId": "retry"})
    assert first == second and first["startJobId"]
    assert (await runtime.tools.invoke(read, "main", binding))["active"] is True
    revoked = await runtime.tools.invoke(
        goal_command("revoke", {"swarmId": team["id"], "expectedDelegationRevision": 1}),
        "main",
        binding,
    )
    assert revoked["revoked"] is True
    assert (await runtime.tools.invoke(read, "main", binding))["active"] is False


@pytest.mark.parametrize("change", ["worker", "research", "home", "lease", "task", "quote"])
async def test_other_roles_and_sources_cannot_start_an_ongoing_goal(delegated_team, change):
    runtime, _, team, _, turn, binding, spec = delegated_team
    await prepare_roles(runtime, team)
    binding = actor(turn, binding)
    role = change if change in {"worker", "research"} else "main"
    args = {"swarmId": team["id"], **{k: v for k, v in spec.items() if k != "commandKey"}}
    if change == "home":
        binding["conversation"] = (await runtime.conversations.create("alice"))["id"]
    elif change == "lease":
        binding["leaseEpoch"] += 1
    elif change == "task":
        binding["taskId"] = "worker-task"
    elif change == "quote":
        args["sourceQuote"] = "invented permission"
    with pytest.raises(DomainError):
        await runtime.tools.invoke(goal_command("enable", args), role, binding)
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_goal_delegations").fetchone()[0]
        )
        == 0
    )
    assert not await runtime.db.call(
        lambda db: row(db, "SELECT id FROM jobs WHERE kind='swarm.goal.start'")
    )


async def test_scheduler_runs_initial_batch_on_original_main_without_a_member_post(delegated_team):
    runtime, _, team, _, turn, binding, spec = delegated_team
    await prepare_roles(runtime, team)
    runtime.settings.workers = 0
    args = {"swarmId": team["id"], **{k: v for k, v in spec.items() if k != "commandKey"}}
    enabled = await runtime.tools.invoke(goal_command("enable", args), "main", actor(turn, binding))
    await finish(runtime, turn)
    await runtime.start()

    def completed(db):
        return row(
            db,
            "SELECT b.*,t.state FROM swarm_coordination_batches b JOIN turns t ON t.id=b.turn_id "
            "WHERE b.delegation_id=? AND t.state='completed'",
            (enabled["delegationId"],),
        )

    await until(runtime.db, completed)
    started = await runtime.db.call(completed)
    assert started["swarm_id"] == team["id"]
    assert (
        await runtime.db.call(
            lambda db: db.execute(
                "SELECT conversation_id FROM turns WHERE id=?", (started["turn_id"],)
            ).fetchone()[0]
        )
        == team["mainConversationId"]
    )


async def test_public_goal_requires_existing_role_tasks(delegated_team):
    runtime, _, team, _, turn, binding, spec = delegated_team
    args = {"swarmId": team["id"], **{k: v for k, v in spec.items() if k != "commandKey"}}
    with pytest.raises(DomainError, match="SWARM_MEMBER_TASK_REQUIRED"):
        await runtime.tools.invoke(goal_command("enable", args), "main", actor(turn, binding))
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_goal_delegations").fetchone()[0]
        )
        == 0
    )


async def test_initial_continuation_cannot_authorize_another_goal(delegated_team):
    runtime, service, team, _, turn, binding, spec = delegated_team
    enabled = await service.enable("alice", team["id"], spec, binding=binding, bootstrap=True)
    await finish(runtime, turn)
    from roami_agent.storage.swarm_goal_start import advance

    started = await runtime.db.call(lambda db: advance(db, enabled["startJobId"]), write=True)
    job = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?", (started["turnId"],)
        )
    )
    current = await runtime.mailbox.claim(job)
    args = {"swarmId": team["id"], **{k: v for k, v in spec.items() if k != "commandKey"}}
    with pytest.raises(DomainError):
        await runtime.tools.invoke(
            goal_command("enable", args),
            "main",
            actor(current, {"conversation": team["mainConversationId"], "turnId": current["id"]}),
        )
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_goal_delegations").fetchone()[0]
        )
        == 1
    )
