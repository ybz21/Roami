"""A rejected Main command cannot leave a team or a replacement coordinator."""

import asyncio

import pytest

from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.swarm_plans import SwarmPlans
from roami_agent.dispatch.tasks import Tasks
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row


@pytest.fixture
async def origin_swarms(store):
    conversations = Conversations(store)
    return SwarmPlans(store, Tasks(store, conversations), conversations, asyncio.Event())


def counts(db):
    return {
        table: db.execute('SELECT count(*) FROM "' + table + '"').fetchone()[0]
        for table in [
            "conversations",
            "branches",
            "swarm_groups",
            "swarm_commands",
            "events",
            "jobs",
        ]
    }


@pytest.mark.parametrize("supplied_main", [True, False])
async def test_missing_user_source_leaves_no_team_receipt_event_or_home(
    origin_swarms, supplied_main
):
    swarms = origin_swarms
    spec = {"name": "No source", "goal": "No user delegated this", "commandKey": "missing-source"}
    if supplied_main:
        spec["mainConversationId"] = (await swarms.conversations.create("alice"))["id"]
    before = await swarms.db.call(counts)
    with pytest.raises(DomainError, match="TASK_REQUIRES_ORIGIN_MESSAGE"):
        await swarms.create("alice", spec, binding={"turnId": "missing"})
    assert await swarms.db.call(counts) == before


async def test_wrong_source_conversation_does_not_persist_a_team(origin_swarms):
    swarms = origin_swarms
    source = await swarms.conversations.create("alice")
    wrong = await swarms.conversations.create("alice")
    turn = await swarms.conversations.accept(
        "alice", source["id"], "source", "Coordinate this goal"
    )
    before = await swarms.db.call(counts)
    with pytest.raises(DomainError, match="TASK_REQUIRES_ORIGIN_MESSAGE"):
        await swarms.create(
            "alice",
            {
                "name": "Wrong Main",
                "goal": "Must not appear",
                "mainConversationId": wrong["id"],
                "commandKey": "wrong",
            },
            binding={"turnId": turn["turnId"]},
        )
    assert await swarms.db.call(counts) == before


@pytest.mark.parametrize("supplied_main", [True, False])
async def test_valid_bound_command_reuses_source_main_and_origin(origin_swarms, supplied_main):
    swarms = origin_swarms
    main = await swarms.conversations.create("alice", "Original goal Main")
    source = await swarms.conversations.accept(
        "alice", main["id"], "source", "Coordinate this goal"
    )
    spec = {"name": "Bound team", "goal": "Coordinate this goal", "commandKey": "bound"}
    if supplied_main:
        spec["mainConversationId"] = main["id"]
    binding = {"turnId": source["turnId"], "conversation": main["id"]}
    created = await swarms.create("alice", spec, binding=binding)
    assert await swarms.create("alice", spec, binding=binding) == created
    assert created["mainConversationId"] == main["id"]
    assert await swarms.db.call(
        lambda db: row(
            db, "SELECT origin_message_id FROM swarm_groups WHERE id=?", (created["id"],)
        )
    ) == {"origin_message_id": source["messageId"]}
    assert (
        await swarms.db.call(
            lambda db: db.execute("SELECT count(*) FROM conversations").fetchone()[0]
        )
        == 1
    )
    assert (
        await swarms.db.call(
            lambda db: db.execute("SELECT count(*) FROM main_conversations").fetchone()[0]
        )
        == 0
    )


async def test_lost_create_receipt_keeps_the_origin_in_the_same_commit(origin_swarms, monkeypatch):
    swarms = origin_swarms
    main = await swarms.conversations.create("alice")
    source = await swarms.conversations.accept(
        "alice", main["id"], "source", "Keep original authority"
    )
    original = swarms.db.call
    injected = False

    async def lose_receipt(fn, *, write=False):
        nonlocal injected
        value = await original(fn, write=write)
        if write and not injected:
            injected = True
            raise ConnectionError("receipt lost after database commit")
        return value

    spec = {
        "name": "One team",
        "goal": "Keep original authority",
        "commandKey": "lost",
        "mainConversationId": main["id"],
    }
    binding = {"turnId": source["turnId"]}
    with monkeypatch.context() as changed:
        changed.setattr(swarms.db, "call", lose_receipt)
        with pytest.raises(ConnectionError):
            await swarms.create("alice", spec, binding=binding)
    value = await original(lambda db: row(db, "SELECT id,origin_message_id FROM swarm_groups"))
    assert value["origin_message_id"] == source["messageId"]
    assert (await swarms.create("alice", spec, binding=binding))["id"] == value["id"]
    assert (
        await original(lambda db: db.execute("SELECT count(*) FROM swarm_groups").fetchone()[0])
        == 1
    )


async def test_empty_bound_context_is_not_reinterpreted_as_a_human_create(origin_swarms):
    swarms = origin_swarms
    before = await swarms.db.call(counts)
    with pytest.raises(DomainError, match="TASK_REQUIRES_ORIGIN_MESSAGE"):
        await swarms.create(
            "alice",
            {"name": "Empty binding", "goal": "Must not create", "commandKey": "empty"},
            binding={},
        )
    assert await swarms.db.call(counts) == before


async def test_completion_cannot_create_a_team_with_an_imported_user_row(origin_swarms):
    swarms = origin_swarms
    main = await swarms.conversations.create("alice")
    source = await swarms.conversations.accept(
        "alice", main["id"], "source", "Original user request"
    )
    await swarms.db.call(
        lambda db: db.execute(
            "UPDATE turns SET trigger_kind='completion' WHERE id=?", (source["turnId"],)
        ),
        write=True,
    )
    before = await swarms.db.call(counts)
    with pytest.raises(DomainError, match="TASK_REQUIRES_ORIGIN_MESSAGE"):
        await swarms.create(
            "alice",
            {
                "name": "Completion group",
                "goal": "Not a new user",
                "commandKey": "completion",
                "mainConversationId": main["id"],
            },
            binding={"turnId": source["turnId"]},
        )
    assert await swarms.db.call(counts) == before


async def test_source_is_revalidated_after_lookup_before_the_write(origin_swarms, monkeypatch):
    swarms = origin_swarms
    main = await swarms.conversations.create("alice")
    source = await swarms.conversations.accept("alice", main["id"], "source", "Revocable request")
    original = swarms.db.call
    forgotten = False

    async def forget_between_calls(fn, *, write=False):
        nonlocal forgotten
        value = await original(fn, write=write)
        if not write and not forgotten:
            forgotten = True
            await original(
                lambda db: db.execute(
                    "UPDATE messages SET deleted_ms=1 WHERE id=?", (source["messageId"],)
                ),
                write=True,
            )
        return value

    before = await original(counts)
    with monkeypatch.context() as changed:
        changed.setattr(swarms.db, "call", forget_between_calls)
        with pytest.raises(DomainError, match="TASK_REQUIRES_ORIGIN_MESSAGE"):
            await swarms.create(
                "alice",
                {
                    "name": "Revoked",
                    "goal": "Must not create",
                    "commandKey": "revoked",
                    "mainConversationId": main["id"],
                },
                binding={"turnId": source["turnId"]},
            )
    assert await original(counts) == before


@pytest.mark.parametrize("state", ["completed", "failed", "interrupted"])
async def test_ended_source_turn_cannot_start_another_team(origin_swarms, state):
    swarms = origin_swarms
    main = await swarms.conversations.create("alice")
    source = await swarms.conversations.accept("alice", main["id"], "source", "Ended request")
    await swarms.db.call(
        lambda db: db.execute("UPDATE turns SET state=? WHERE id=?", (state, source["turnId"])),
        write=True,
    )
    before = await swarms.db.call(counts)
    with pytest.raises(DomainError, match="TASK_REQUIRES_ORIGIN_MESSAGE"):
        await swarms.create(
            "alice",
            {
                "name": "Ended",
                "goal": "No late team",
                "commandKey": "ended",
                "mainConversationId": main["id"],
            },
            binding={"turnId": source["turnId"]},
        )
    assert await swarms.db.call(counts) == before


async def test_forgotten_source_is_not_reused_for_a_team(origin_swarms):
    swarms = origin_swarms
    main = await swarms.conversations.create("alice")
    source = await swarms.conversations.accept("alice", main["id"], "source", "Forgotten request")
    await swarms.db.call(
        lambda db: db.execute(
            "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'forgotten',1)",
            (source["messageId"],),
        ),
        write=True,
    )
    before = await swarms.db.call(counts)
    with pytest.raises(DomainError, match="TASK_REQUIRES_ORIGIN_MESSAGE"):
        await swarms.create(
            "alice",
            {
                "name": "Forgotten",
                "goal": "No omitted authority",
                "commandKey": "forgotten",
                "mainConversationId": main["id"],
            },
            binding={"turnId": source["turnId"]},
        )
    assert await swarms.db.call(counts) == before
