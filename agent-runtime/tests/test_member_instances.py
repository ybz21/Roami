"""Idle members keep their own context without acquiring Main authority or fake tasks."""

import sqlite3

import pytest
from test_swarm_members import finish_round, register, team

from roami_agent.conversation.conversation_identity import conversation_identity
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row

__all__ = ["team"]


async def test_idle_native_member_is_previewable_without_task_or_main_authority(team, store):
    runtime, group = team
    created = await register(runtime, group)
    member_id = created["members"][0]["id"]
    member = (await runtime.swarms.member("alice", group["id"], member_id))["member"]
    instance = member["instance"]
    assert (
        instance["state"] == "idle"
        and instance["taskId"] is None
        and instance["nativeSessionId"] is None
    )
    assert instance["conversationId"] != group["mainConversationId"]
    assert not await runtime.tasks.list("alice")
    identity = await store.call(
        lambda db: conversation_identity(db, "alice", instance["conversationId"])
    )
    assert identity["kind"] == "member" and identity["taskId"] is None
    assert identity["memberId"] == member_id and identity["instanceId"] == instance["id"]
    assert instance["conversationId"] not in [
        c["id"] for c in await runtime.conversations.list("alice")
    ]
    with pytest.raises(DomainError, match="NATIVE_SESSION_USE_TASK_CHANNEL"):
        await runtime.chat.submit(
            "alice", instance["conversationId"], "not-main", "Start a coordinator"
        )
    with pytest.raises(DomainError, match="SWARM_MAIN_REQUIRED"):
        await runtime.swarms.create(
            "alice",
            {
                "name": "Wrong Main",
                "goal": "Must reject",
                "commandKey": "wrong-main",
                "mainConversationId": instance["conversationId"],
            },
        )
    assert (
        await store.call(
            lambda db: db.execute(
                "SELECT COUNT(*) FROM turns WHERE conversation_id=?", (instance["conversationId"],)
            ).fetchone()[0]
        )
        == 0
    )


async def test_first_assignment_and_three_rounds_reuse_reserved_native_member_conversation(
    team, store
):
    runtime, group = team
    created = await register(runtime, group)
    member_id = created["members"][0]["id"]
    initial = (await runtime.swarms.member("alice", group["id"], member_id))["member"]["instance"]
    await runtime.swarms.plan(
        "alice",
        group["id"],
        {
            "commandKey": "work",
            "expectedRevision": 2,
            "items": [
                {
                    "memberId": member_id,
                    "member": "research",
                    "executor": "native",
                    "title": "Read references",
                    "goal": "Read the reference",
                    "acceptance": "Verify the reference",
                }
            ],
        },
    )
    await runtime.swarms.advance({"id": "advance", "aggregate_id": group["id"]})
    work = (await runtime.swarms.snapshot("alice", group["id"]))["work"][0]
    for revision in (1, 2, 3):
        await finish_round(runtime, work, revision)
        member = (await runtime.swarms.member("alice", group["id"], member_id))["member"]
        current = member["instance"]
        assert (
            current["id"] == initial["id"]
            and current["conversationId"] == initial["conversationId"]
            and current["branchId"] == initial["branchId"]
        )
        assert current["taskId"] == work["task_id"] and current["nativeSessionId"]
        native = await store.call(
            lambda db: row(db, "SELECT * FROM native_sessions WHERE task_id=?", (work["task_id"],))
        )
        assert (
            native["conversation_id"] == initial["conversationId"]
            and native["branch_id"] == initial["branchId"]
        )
        if revision < 3:
            await runtime.tasks.revisions.request(
                "alice",
                work["task_id"],
                f"Read reference {revision + 1}",
                revision,
                f"round-{revision + 1}",
            )
            await runtime.tasks.revisions.advance()
    assert (
        await store.call(
            lambda db: db.execute("SELECT COUNT(*) FROM swarm_member_instances").fetchone()[0]
        )
        == 1
    )
    assert await store.call(lambda db: db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]) == 1
    assert (await runtime.conversations.main("alice"))["id"] == group["mainConversationId"]


async def test_member_instance_database_cannot_become_home_or_project_main(team, store):
    runtime, group = team
    member_id = (await register(runtime, group))["members"][0]["id"]
    instance = (await runtime.swarms.member("alice", group["id"], member_id))["member"]["instance"]
    for sql, args in [
        (
            "UPDATE main_conversations SET conversation_id=? WHERE owner_id=?",
            (instance["conversationId"], "alice"),
        ),
        (
            "INSERT INTO project_okr_conversations VALUES(?,?,?)",
            (instance["conversationId"], "alice", "other-project"),
        ),
        (
            "UPDATE swarm_groups SET conversation_id=? WHERE id=?",
            (instance["conversationId"], group["id"]),
        ),
    ]:
        with pytest.raises(sqlite3.IntegrityError, match="CONVERSATION_IDENTITY_CONFLICT"):
            await store.call(lambda db, sql=sql, args=args: db.execute(sql, args), write=True)
    other = await runtime.conversations.create("bob")
    with pytest.raises(sqlite3.IntegrityError, match="MEMBER_INSTANCE_BINDING_CONFLICT"):
        await store.call(
            lambda db: db.execute(
                "UPDATE swarm_member_instances SET conversation_id=? WHERE id=?",
                (other["id"], instance["id"]),
            ),
            write=True,
        )
    with pytest.raises(DomainError, match="SWARM_NOT_FOUND"):
        await runtime.swarms.member("bob", group["id"], member_id)


async def test_home_recovery_never_selects_an_idle_member_conversation(team, store):
    runtime, group = team
    member_id = (await register(runtime, group))["members"][0]["id"]
    instance = (await runtime.swarms.member("alice", group["id"], member_id))["member"]["instance"]
    await store.call(
        lambda db: db.execute("DELETE FROM main_conversations WHERE owner_id='alice'"), write=True
    )
    home = await runtime.conversations.main("alice")
    assert home["id"] not in {instance["conversationId"], group["mainConversationId"]}
    assert (await runtime.swarms.snapshot("alice", group["id"]))["mainConversationId"] == group[
        "mainConversationId"
    ]


async def test_deleted_idle_member_keeps_original_binding_without_replacement(team, store):
    runtime, group = team
    member_id = (await register(runtime, group))["members"][0]["id"]
    original = (await runtime.swarms.member("alice", group["id"], member_id))["member"]["instance"]
    await store.call(
        lambda db: db.execute(
            "UPDATE conversations SET deleted_ms=1 WHERE id=?", (original["conversationId"],)
        ),
        write=True,
    )
    await register(runtime, group, key="same-role-after-close", revision=2)
    current = (await runtime.swarms.member("alice", group["id"], member_id))["member"]["instance"]
    assert (
        current["id"] == original["id"]
        and current["conversationId"] == original["conversationId"]
        and current["state"] == "closed"
    )
    assert not await runtime.tasks.list("alice")
    assert (
        await store.call(
            lambda db: db.execute("SELECT COUNT(*) FROM swarm_member_instances").fetchone()[0]
        )
        == 1
    )


async def test_model_admission_cannot_promote_member_context_via_lower_level_intake(team, store):
    from roami_agent.context.prompt_builder import PromptBuilder

    runtime, group = team
    member_id = (await register(runtime, group))["members"][0]["id"]
    instance = (await runtime.swarms.member("alice", group["id"], member_id))["member"]["instance"]
    builder = PromptBuilder(store, None, runtime.settings)
    turn = {
        "conversation_id": instance["conversationId"],
        "branch_id": instance["branchId"],
        "owner_id": "alice",
        "id": "unbound-turn",
        "created_ms": 1,
    }
    with pytest.raises(DomainError, match="NATIVE_SESSION_USE_TASK_CHANNEL"):
        await builder.build(turn, "Main instructions", [], None)
    with pytest.raises(DomainError, match="MEMBER_INSTANCE_BINDING_CONFLICT"):
        await builder.build(
            {**turn, "executionRunId": "foreign-attempt"}, "Main instructions", [], None
        )
