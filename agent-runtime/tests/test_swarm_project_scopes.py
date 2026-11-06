"""Project names, receipts and Main messages share one durable scope."""

import asyncio

import pytest

from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.swarm_plans import SwarmPlans
from roami_agent.dispatch.tasks import Tasks
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row


@pytest.fixture
async def scoped_swarms(store):
    conversations = Conversations(store)
    swarms = SwarmPlans(store, Tasks(store, conversations), conversations, asyncio.Event())

    class Intake:
        async def submit(self, owner, cid, key, text):
            return {"kind": "message", **await conversations.accept(owner, cid, key, text)}

    swarms.chat = Intake()
    return swarms


async def create_project(swarms, pid, *, name="Operations", key="create"):
    return await swarms.create(
        "alice",
        {
            "name": name,
            "goal": "Coordinate " + pid,
            "target": {"kind": "project", "projectId": pid},
            "commandKey": key,
        },
    )


async def test_two_projects_reuse_names_and_command_keys_with_independent_mains(scoped_swarms):
    swarms = scoped_swarms
    first = await create_project(swarms, "project-a")
    second = await create_project(swarms, "project-b")
    assert first["id"] != second["id"]
    assert first["mainConversationId"] != second["mainConversationId"]
    assert await create_project(swarms, "project-a") == first
    assert await create_project(swarms, "project-b") == second
    for created, pid in [(first, "project-a"), (second, "project-b")]:
        value = await swarms.snapshot("alice", created["id"])
        assert value["scope"] == {"kind": "project", "projectId": pid}
        assert len(value["posts"]) == 1
        paused = await swarms.control(
            "alice",
            created["id"],
            {"commandKey": "pause", "expectedRevision": 1, "action": "pause"},
        )
        assert paused["revision"] == 2
        assert (
            await swarms.control(
                "alice",
                created["id"],
                {"commandKey": "pause", "expectedRevision": 1, "action": "pause"},
            )
            == paused
        )
        with pytest.raises(DomainError, match="REQUEST_KEY_CONFLICT"):
            await swarms.control(
                "alice",
                created["id"],
                {"commandKey": "pause", "expectedRevision": 2, "action": "resume"},
            )


async def test_same_message_key_in_two_projects_delivers_to_each_original_main(scoped_swarms):
    swarms = scoped_swarms
    first = await create_project(swarms, "project-a", name="A", key="create-a")
    second = await create_project(swarms, "project-b", name="B", key="create-b")
    sent = []
    for created, text in [(first, "Review A"), (second, "Review B")]:
        spec = {"commandKey": "message", "text": text}
        result = await swarms.send("alice", created["id"], spec)
        assert await swarms.send("alice", created["id"], spec) == result
        turn = await swarms.db.call(
            lambda db, tid=result["turnId"]: row(
                db, "SELECT conversation_id FROM turns WHERE id=?", (tid,)
            )
        )
        assert turn["conversation_id"] == created["mainConversationId"]
        sent.append(result["turnId"])
    assert sent[0] != sent[1]


@pytest.mark.parametrize("foreign", ["home", "project-b"])
async def test_project_team_cannot_bind_home_or_another_project_main(scoped_swarms, foreign):
    swarms = scoped_swarms
    main = (
        await swarms.conversations.main("alice")
        if foreign == "home"
        else await swarms.conversations.create("alice", project_id=foreign)
    )
    with pytest.raises(
        DomainError,
        match="PROJECT_OKR_MAIN_CONFLICT" if foreign == "home" else "PROJECT_OKR_TEAM_CONFLICT",
    ):
        await swarms.create(
            "alice",
            {
                "name": "Wrong",
                "goal": "Project A",
                "target": {"kind": "project", "projectId": "project-a"},
                "mainConversationId": main["id"],
                "commandKey": "wrong",
            },
        )
    assert not await swarms.list("alice")


async def test_members_keep_independent_instances_and_replay_original_registration(scoped_swarms):
    swarms = scoped_swarms
    first = await create_project(swarms, "project-a")
    second = await create_project(swarms, "project-b")
    instances = []
    for created in [first, second]:
        spec = {
            "commandKey": "roles",
            "expectedRevision": 1,
            "members": [
                {
                    "name": "analysis",
                    "executor": "native",
                    "duty": "Analyze this project's evidence",
                }
            ],
        }
        registered = await swarms.register_members("alice", created["id"], spec)
        assert await swarms.register_members("alice", created["id"], spec) == registered
        member = (await swarms.snapshot("alice", created["id"]))["members"][0]
        assert member["memoryPath"] == "members/" + member["id"] + "/memory.md"
        instances.append(member["instance"]["conversationId"])
    assert len({*instances, first["mainConversationId"], second["mainConversationId"]}) == 4
    with pytest.raises(DomainError, match="SWARM_MAIN_REQUIRED"):
        await swarms.post(
            "alice",
            first["id"],
            {"commandKey": "foreign-post", "text": "Must not appear"},
            binding={"conversation": second["mainConversationId"]},
        )
    assert not any(
        post["text"] == "Must not appear"
        for post in (await swarms.snapshot("alice", first["id"]))["posts"]
    )


async def test_new_message_lost_delivery_receipt_recovers_original_turn(scoped_swarms):
    swarms = scoped_swarms
    created = await create_project(swarms, "project-a")
    accepted = []

    class LostReceipt:
        async def submit(self, owner, cid, key, text):
            accepted.append(await swarms.conversations.accept(owner, cid, key, text))
            raise ConnectionError("receipt lost after acceptance")

    swarms.chat = LostReceipt()
    spec = {"commandKey": "retry-message", "text": "Read original evidence"}
    with pytest.raises(ConnectionError):
        await swarms.send("alice", created["id"], spec)
    stored = await swarms.db.call(
        lambda db: row(
            db, "SELECT delivery_key,delivery_json FROM swarm_posts WHERE text=?", (spec["text"],)
        )
    )
    assert stored["delivery_key"] and stored["delivery_json"] is None
    recovered = SwarmPlans(swarms.db, swarms.tasks, swarms.conversations, asyncio.Event())

    class Retry:
        async def submit(self, owner, cid, key, text):
            assert key == stored["delivery_key"]
            return {"kind": "message", **await swarms.conversations.accept(owner, cid, key, text)}

    recovered.chat = Retry()
    receipt = await recovered.send("alice", created["id"], spec)
    assert receipt["turnId"] == accepted[0]["turnId"] and receipt["reused"] is True
    assert await recovered.send("alice", created["id"], spec) == receipt
    assert (
        await swarms.db.call(
            lambda db: db.execute(
                "SELECT count(*) FROM messages WHERE role='user' AND json_extract(content_json,'$.text')=?",
                (spec["text"],),
            ).fetchone()[0]
        )
        == 1
    )


async def test_same_scope_name_stays_unique_and_scope_cannot_be_retargeted(scoped_swarms):
    import sqlite3

    swarms = scoped_swarms
    created = await create_project(swarms, "project-a")
    with pytest.raises(DomainError, match="SWARM_NAME_EXISTS"):
        await create_project(swarms, "project-a", key="another-create")
    for sql, params in [
        (
            "UPDATE swarm_groups SET target_json=? WHERE id=?",
            ('{"kind":"project","projectId":"project-b"}', created["id"]),
        ),
        ("UPDATE swarm_groups SET scope_project_id=NULL WHERE id=?", (created["id"],)),
    ]:
        with pytest.raises(sqlite3.IntegrityError, match="SWARM_PROJECT_SCOPE_CONFLICT"):
            await swarms.db.call(
                lambda db, sql=sql, params=params: db.execute(sql, params), write=True
            )
    assert (await swarms.snapshot("alice", created["id"]))["scope"]["projectId"] == "project-a"


async def test_unbound_legacy_project_waits_for_trusted_main_restore(scoped_swarms):
    from roami_agent.protocol.serialization import encoded

    swarms = scoped_swarms
    sid = "sw-" + "d" * 32

    def legacy(db):
        main = Conversations._new(db, "alice", "Original legacy Main")
        db.execute(
            "INSERT INTO project_okr_conversations VALUES(?,?,?)",
            (main["id"], "alice", "legacy-project"),
        )
        db.execute(
            "INSERT INTO swarm_groups(id,owner_id,name,conversation_id,goal,target_json,created_ms,updated_ms) VALUES(?,'alice','Legacy',?,'Original goal',?,1,1)",
            (sid, main["id"], encoded({"kind": "project", "projectId": "legacy-project"})),
        )
        db.execute(
            "INSERT INTO swarm_work_items(id,swarm_id,member_name,executor,title,goal,acceptance) VALUES('old-work',?,'analysis','native','Analyze','Original task','Verify')",
            (sid,),
        )
        return main

    main = await swarms.db.call(legacy, write=True)
    assert (await swarms.snapshot("alice", sid))["scope"] == {"kind": "unbound"}
    with pytest.raises(DomainError, match="SWARM_PROJECT_SCOPE_REQUIRED"):
        await swarms.post("alice", sid, {"commandKey": "new-post", "text": "Do not dispatch"})
    with pytest.raises(DomainError, match="SWARM_PROJECT_SCOPE_REQUIRED"):
        await swarms.memory_write(
            "alice", sid, {"content": "No guessed memory", "expectedSha256": "a" * 64}
        )
    await swarms.advance({"id": "old-job", "aggregate_id": sid})
    blocked = await swarms.db.call(
        lambda db: row(
            db, "SELECT task_id,dispatch_error FROM swarm_work_items WHERE id='old-work'"
        )
    )
    assert blocked == {"task_id": None, "dispatch_error": "SWARM_PROJECT_SCOPE_REQUIRED"}
    assert (await swarms.conversations.create("alice", project_id="legacy-project", swarm_id=sid))[
        "id"
    ] == main["id"]
    assert (await swarms.snapshot("alice", sid))["scope"] == {
        "kind": "project",
        "projectId": "legacy-project",
    }
    assert await swarms.db.call(
        lambda db: row(
            db, "SELECT task_id,dispatch_error FROM swarm_work_items WHERE id='old-work'"
        )
    ) == {"task_id": None, "dispatch_error": None}
    jobs = await swarms.db.call(
        lambda db: db.execute(
            "SELECT count(*) FROM jobs WHERE kind='swarm.advance' AND aggregate_id=?", (sid,)
        ).fetchone()[0]
    )
    await swarms.conversations.create("alice", project_id="legacy-project", swarm_id=sid)
    assert (
        await swarms.db.call(
            lambda db: db.execute(
                "SELECT count(*) FROM jobs WHERE kind='swarm.advance' AND aggregate_id=?", (sid,)
            ).fetchone()[0]
        )
        == jobs
        == 1
    )


async def test_ambiguous_legacy_mains_are_not_resolved_by_latest_message(scoped_swarms):
    swarms = scoped_swarms

    def legacy(db):
        for title in ["Original", "Newer unrelated history"]:
            main = Conversations._new(db, "alice", title)
            db.execute(
                "INSERT INTO project_okr_conversations VALUES(?,?,?)",
                (main["id"], "alice", "ambiguous"),
            )

    await swarms.db.call(legacy, write=True)
    with pytest.raises(DomainError, match="PROJECT_OKR_MAIN_CONFLICT"):
        await swarms.conversations.create("alice", project_id="ambiguous")
    assert (
        await swarms.db.call(
            lambda db: db.execute("SELECT count(*) FROM conversations").fetchone()[0]
        )
        == 2
    )
    assert (
        await swarms.db.call(
            lambda db: db.execute("SELECT count(*) FROM project_okr_mains").fetchone()[0]
        )
        == 0
    )
