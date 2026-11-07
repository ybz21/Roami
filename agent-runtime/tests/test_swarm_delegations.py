"""Autonomous coordination inherits a real scoped user goal, never a group post."""

import json

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.dispatch.swarm_delegations import SwarmDelegations
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row

GOAL = "每天整理X和B站草稿、采集数据并复盘；发布仍需用户具体确认。"


@pytest.fixture
async def delegated_team(store, request):
    runtime = Runtime(store, ConversationModel())
    main = await runtime.conversations.create("alice", project_id="project-a")
    accepted = await runtime.conversations.accept("alice", main["id"], "goal", GOAL)
    job = await store.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?", (accepted["turnId"],)
        )
    )
    turn = await runtime.mailbox.claim(job)
    binding = {"conversation": main["id"], "turnId": turn["id"]}
    created = await runtime.swarms.create(
        "alice",
        {
            "name": "Promotion",
            "goal": GOAL,
            "mainConversationId": main["id"],
            "target": {"kind": "project", "projectId": "project-a"},
            "commandKey": "create",
        },
        binding=binding,
    )
    await runtime.swarms.register_members(
        "alice",
        created["id"],
        {
            "commandKey": "roles",
            "expectedRevision": 1,
            "members": [
                {
                    "name": name,
                    "executor": getattr(request, "param", "codex"),
                    "duty": "只处理本项目",
                }
                for name in ["X维护", "B站维护", "数据分析"]
            ],
        },
    )
    members = [
        m["id"]
        for m in (await runtime.swarms.snapshot("alice", created["id"], include_memory=False))[
            "members"
        ]
    ]
    spec = {
        "commandKey": "enable",
        "expectedDelegationRevision": 0,
        "sourceQuote": GOAL,
        "memberIds": members,
    }
    service = SwarmDelegations(store)
    try:
        yield runtime, service, created, accepted, turn, binding, spec
    finally:
        await runtime.close()


async def finish(runtime, turn):
    mid = await runtime.journal.start(turn)
    await runtime.journal.finish(turn, mid, "目标已记录", [], None, 1, final=True, completion=None)
    return mid


async def test_delegation_keeps_original_main_members_and_source_after_user_turn_ends(
    delegated_team,
):
    runtime, service, team, accepted, turn, binding, spec = delegated_team
    before = await runtime.db.call(
        lambda db: [
            db.execute("SELECT count(*) FROM " + name).fetchone()[0]
            for name in ["conversations", "turns", "jobs", "swarm_members"]
        ]
    )
    enabled = await service.enable("alice", team["id"], spec, binding=binding)
    assert await service.enable("alice", team["id"], spec, binding=binding) == enabled
    after = await runtime.db.call(
        lambda db: [
            db.execute("SELECT count(*) FROM " + name).fetchone()[0]
            for name in ["conversations", "turns", "jobs", "swarm_members"]
        ]
    )
    assert after == before
    await finish(runtime, turn)
    actual = await service.current("alice", team["id"], enabled["delegationId"])
    assert (
        actual["mainConversationId"] == team["mainConversationId"]
        and actual["projectId"] == "project-a"
    )
    assert actual["source_message_id"] == accepted["messageId"] and actual["source_quote"] == GOAL
    assert json.loads(actual["member_ids_json"]) == spec["memberIds"]


@pytest.mark.parametrize(
    "change",
    [
        {"sourceQuote": "用户允许直接发布"},
        {"memberIds": ["foreign-member"]},
        {"expectedDelegationRevision": 1},
    ],
)
async def test_invented_goal_unknown_member_or_stale_revision_cannot_grant(delegated_team, change):
    runtime, service, team, _, _, binding, spec = delegated_team
    with pytest.raises(DomainError):
        await service.enable("alice", team["id"], {**spec, **change}, binding=binding)
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_goal_delegations").fetchone()[0]
        )
        == 0
    )


@pytest.mark.parametrize(
    "binding_change",
    [
        {"taskId": "member-task"},
        {"conversation": "other-main"},
        {"turnId": "missing"},
        {"leaseEpoch": 0},
        {"leaseEpoch": True},
    ],
)
async def test_only_actual_current_user_turn_in_original_main_can_delegate(
    delegated_team, binding_change
):
    runtime, service, team, _, _, binding, spec = delegated_team
    with pytest.raises(DomainError):
        await service.enable("alice", team["id"], spec, binding={**binding, **binding_change})
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_goal_delegations").fetchone()[0]
        )
        == 0
    )


async def test_durable_stop_prevents_goal_delegation(delegated_team):
    runtime, service, team, _, _, binding, spec = delegated_team
    await runtime.chat.interrupt("alice", team["mainConversationId"], "stop")
    with pytest.raises(DomainError, match="TURN_INTERRUPTED"):
        await service.enable("alice", team["id"], spec, binding=binding)


async def test_scheduled_user_row_is_not_a_new_human_goal(delegated_team):
    runtime, service, team, _, turn, _, spec = delegated_team
    await finish(runtime, turn)
    scheduled = await runtime.conversations.accept(
        "alice", team["mainConversationId"], "scheduled", GOAL, wake_project="project-a"
    )
    job = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?",
            (scheduled["turnId"],),
        )
    )
    await runtime.mailbox.claim(job)
    with pytest.raises(DomainError, match="SWARM_DELEGATION_USER_REQUEST_REQUIRED"):
        await service.enable(
            "alice",
            team["id"],
            spec,
            binding={"conversation": team["mainConversationId"], "turnId": scheduled["turnId"]},
        )


async def test_completion_with_imported_user_row_cannot_delegate(delegated_team):
    runtime, service, team, _, turn, binding, spec = delegated_team
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE turns SET trigger_kind='completion' WHERE id=?", (turn["id"],)
        ),
        write=True,
    )
    with pytest.raises(DomainError, match="SWARM_DELEGATION_USER_REQUEST_REQUIRED"):
        await service.enable("alice", team["id"], spec, binding=binding)


async def test_forgotten_user_source_invalidates_stored_goal(delegated_team):
    runtime, service, team, accepted, _, binding, spec = delegated_team
    enabled = await service.enable("alice", team["id"], spec, binding=binding)
    await runtime.db.call(
        lambda db: db.execute(
            "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'forgotten',1)",
            (accepted["messageId"],),
        ),
        write=True,
    )
    with pytest.raises(DomainError, match="SWARM_DELEGATION_SOURCE_FORGOTTEN"):
        await service.current("alice", team["id"], enabled["delegationId"])


async def test_goal_pause_and_explicit_human_revocation_keep_the_original_record(delegated_team):
    runtime, service, team, _, turn, binding, spec = delegated_team
    enabled = await service.enable("alice", team["id"], spec, binding=binding)
    paused = await runtime.swarms.control(
        "alice", team["id"], {"commandKey": "pause", "expectedRevision": 2, "action": "pause"}
    )
    with pytest.raises(DomainError, match="SWARM_COORDINATION_PAUSED"):
        await service.current("alice", team["id"])
    await runtime.swarms.control(
        "alice",
        team["id"],
        {"commandKey": "resume", "expectedRevision": paused["revision"], "action": "resume"},
    )
    assert (await service.current("alice", team["id"]))["id"] == enabled["delegationId"]
    await finish(runtime, turn)
    revoke = await runtime.conversations.accept(
        "alice", team["mainConversationId"], "revoke", "停止自动协调"
    )
    job = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?", (revoke["turnId"],)
        )
    )
    await runtime.mailbox.claim(job)
    result = await service.revoke(
        "alice",
        team["id"],
        {"commandKey": "revoke", "expectedDelegationRevision": 1},
        binding={"conversation": team["mainConversationId"], "turnId": revoke["turnId"]},
    )
    assert result["revoked"] is True
    with pytest.raises(DomainError, match="SWARM_DELEGATION_REQUIRED"):
        await service.current("alice", team["id"])
    assert (
        await runtime.db.call(
            lambda db: db.execute(
                "SELECT count(*) FROM swarm_goal_delegations WHERE id=? AND revoked_by_message_id=?",
                (enabled["delegationId"], revoke["messageId"]),
            ).fetchone()[0]
        )
        == 1
    )


async def test_a_real_member_from_another_project_cannot_join_this_delegation(delegated_team):
    runtime, service, team, _, _, binding, spec = delegated_team
    other = await runtime.swarms.create(
        "alice",
        {
            "name": "Other",
            "goal": "Other project",
            "target": {"kind": "project", "projectId": "project-b"},
            "commandKey": "other",
        },
    )
    await runtime.swarms.register_members(
        "alice",
        other["id"],
        {
            "commandKey": "roles",
            "expectedRevision": 1,
            "members": [{"name": "Data", "executor": "codex", "duty": "Other project only"}],
        },
    )
    foreign = (await runtime.swarms.snapshot("alice", other["id"], include_memory=False))[
        "members"
    ][0]["id"]
    with pytest.raises(DomainError, match="SWARM_MEMBER_REQUIRED"):
        await service.enable("alice", team["id"], {**spec, "memberIds": [foreign]}, binding=binding)
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_goal_delegations").fetchone()[0]
        )
        == 0
    )


@pytest.mark.parametrize("include_new_goal", [True, False])
async def test_current_branch_must_actually_include_the_latest_goal_source(
    delegated_team, include_new_goal
):
    runtime, service, team, _, turn, binding, spec = delegated_team
    first = await service.enable("alice", team["id"], spec, binding=binding)
    old_cut = await finish(runtime, turn)
    accepted = await runtime.conversations.accept(
        "alice", team["mainConversationId"], "renew", "继续执行：" + GOAL
    )
    job = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?", (accepted["turnId"],)
        )
    )
    newer = await runtime.mailbox.claim(job)
    renewed = await service.enable(
        "alice",
        team["id"],
        {**spec, "commandKey": "renew", "expectedDelegationRevision": 1},
        binding={"conversation": team["mainConversationId"], "turnId": newer["id"]},
    )
    new_cut = await finish(runtime, newer)
    await runtime.conversations.fork(
        "alice", team["mainConversationId"], new_cut if include_new_goal else old_cut
    )
    if include_new_goal:
        assert (await service.current("alice", team["id"]))["id"] == renewed["delegationId"]
    else:
        with pytest.raises(DomainError, match="SWARM_DELEGATION_SOURCE_FORGOTTEN"):
            await service.current("alice", team["id"])
    assert (
        await runtime.db.call(
            lambda db: db.execute(
                "SELECT count(*) FROM swarm_goal_delegations WHERE id=? AND revoked_ms IS NOT NULL",
                (first["delegationId"],),
            ).fetchone()[0]
        )
        == 1
    )
