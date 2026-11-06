"""Upgrade real old collaboration facts without replaying work or changing identity."""

import asyncio
import hashlib
import sqlite3

import pytest

from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.swarm_plans import SwarmPlans
from roami_agent.dispatch.tasks import Tasks
from roami_agent.protocol.serialization import encoded
from roami_agent.storage import database as database_module
from roami_agent.storage import migrations
from roami_agent.storage.database import row


def command(db, owner, key, payload, receipt):
    db.execute(
        "INSERT INTO swarm_commands VALUES(?,?,?,?)",
        (owner, key, hashlib.sha256(encoded(payload).encode()).hexdigest(), encoded(receipt)),
    )


async def legacy_database(tmp_path, monkeypatch):
    root = tmp_path / "legacy"
    path = root / "database/agents/runtime.db"
    with monkeypatch.context() as old:
        old.setattr(migrations, "SCHEMA_VERSION", 22)
        old.setattr(database_module, "SCHEMA_VERSION", 22)
        database = database_module.Database(path, root, managed=False)
        await database.open()
    conversations = Conversations(database)

    def seed(db):
        result = []
        for suffix, pid in [("a", "project-a"), ("b", "project-b")]:
            main = Conversations._new(db, "alice", "Original " + suffix)
            db.execute(
                "INSERT INTO project_okr_conversations VALUES(?,?,?)", (main["id"], "alice", pid)
            )
            if suffix == "a":
                db.execute(
                    "INSERT INTO project_okr_mains VALUES(?,?,?)", ("alice", pid, main["id"])
                )
            sid = "sw-" + suffix * 32
            target = {"kind": "project", "projectId": pid}
            db.execute(
                "INSERT INTO swarm_groups(id,owner_id,name,conversation_id,goal,target_json,created_ms,updated_ms) VALUES(?,'alice',?,?,?, ?,1,1)",
                (sid, "Original " + suffix, main["id"], "Original goal", encoded(target)),
            )
            spec = {
                "name": "Original " + suffix,
                "goal": "Original goal",
                "target": target,
                "mainConversationId": main["id"],
                "commandKey": "create-" + suffix,
            }
            receipt = {"id": sid, "mainConversationId": main["id"], "revision": 1}
            command(db, "alice", spec["commandKey"], spec, receipt)
            result.append({"id": sid, "main": main, "spec": spec, "receipt": receipt})
        return result

    groups = await database.call(seed, write=True)
    sent = await conversations.accept(
        "alice", groups[0]["main"]["id"], "swarm.message:message", "Review old A"
    )
    task = await Tasks(database, conversations).create(
        "alice",
        groups[0]["main"]["id"],
        "Original task",
        key="original-task",
        executor="codex",
        origin_message_id=sent["messageId"],
    )

    def history(db):
        sid = groups[0]["id"]
        db.execute(
            "UPDATE swarm_groups SET origin_message_id=? WHERE id=?", (sent["messageId"], sid)
        )
        db.execute(
            "INSERT INTO swarm_work_items(id,swarm_id,member_name,executor,title,goal,acceptance,task_id) VALUES('original-work',?,'analysis','codex','Analyze','Read original','Verify',?)",
            (sid, task["id"]),
        )
        db.execute(
            "INSERT INTO swarm_members(id,swarm_id,name,executor,duty,current_work_id,created_ms) VALUES('original-member',?,'analysis','codex','Original role','original-work',1)",
            (sid,),
        )
        db.execute("INSERT INTO swarm_member_work VALUES('original-member','original-work')")
        db.execute(
            "INSERT INTO swarm_member_rounds(member_id,task_id,revision,source_message_id,request_text,created_ms) VALUES('original-member',?,1,?,'Original assignment',1)",
            (task["id"], sent["messageId"]),
        )
        post = db.execute(
            "INSERT INTO swarm_posts(swarm_id,author,text,created_ms) VALUES(?,'human','Review old A',1)",
            (sid,),
        ).lastrowid
        command(
            db,
            "alice",
            "message",
            {"swarmId": sid, "commandKey": "message", "text": "Review old A", "binding": None},
            {"id": post, "swarmId": sid},
        )
        db.execute(
            "INSERT INTO swarm_memories VALUES(?,?,?,?,?)",
            (sid, "Original team knowledge", "original-hash", 1, "alice"),
        )

    await database.call(history, write=True)
    await database.call(
        lambda db: db.executescript(
            "CREATE VIEW legacy_team_messages AS SELECT g.id,p.text FROM swarm_groups g JOIN swarm_posts p ON p.swarm_id=g.id;"
            "CREATE INDEX legacy_team_goal ON swarm_groups(goal);"
        )
    )
    await database.close()
    return root, path, groups, {"kind": "message", **sent, "reused": True}


def facts(db):
    result = {}
    for (table,) in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ):
        if table in {"schema_meta", "swarm_groups", "swarm_commands", "swarm_posts"}:
            continue
        result[table] = sorted(
            [tuple(row) for row in db.execute('SELECT * FROM "' + table + '"')], key=repr
        )
    return result


async def test_schema22_upgrade_keeps_all_facts_and_old_unknown_message_receipt(
    tmp_path, monkeypatch
):
    root, path, groups, sent = await legacy_database(tmp_path, monkeypatch)
    with sqlite3.connect(path) as before:
        original = facts(before)
        commands = before.execute(
            "SELECT owner_id,command_key,digest,receipt_json FROM swarm_commands ORDER BY command_key"
        ).fetchall()
        triggers = before.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
        views = before.execute("SELECT name,sql FROM sqlite_master WHERE type='view'").fetchall()
    upgraded = database_module.Database(path, root, managed=False)
    await upgraded.open()
    try:
        assert await upgraded.call(facts) == original
        assert (
            await upgraded.call(
                lambda db: [
                    tuple(row)
                    for row in db.execute(
                        "SELECT owner_id,command_key,digest,receipt_json FROM swarm_commands ORDER BY command_key"
                    )
                ]
            )
            == commands
        )
        assert await upgraded.call(lambda db: db.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
        assert (
            await upgraded.call(lambda db: db.execute("PRAGMA foreign_key_check").fetchall()) == []
        )
        for name, sql in triggers:
            assert (
                await upgraded.call(
                    lambda db, name=name: db.execute(
                        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,)
                    ).fetchone()[0]
                )
                == sql
            )
        for name, sql in views:
            assert (
                await upgraded.call(
                    lambda db, name=name: db.execute(
                        "SELECT sql FROM sqlite_master WHERE type='view' AND name=?", (name,)
                    ).fetchone()[0]
                )
                == sql
            )
        assert (
            await upgraded.call(
                lambda db: db.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name='legacy_team_goal'"
                ).fetchone()[0]
            )
            == "legacy_team_goal"
        )
        conv = Conversations(upgraded)
        swarms = SwarmPlans(upgraded, Tasks(upgraded, conv), conv, asyncio.Event())
        assert await swarms.create("alice", groups[0]["spec"]) == groups[0]["receipt"]
        restored = await conv.create("alice", project_id="project-b", swarm_id=groups[1]["id"])
        assert restored["id"] == groups[1]["main"]["id"]
        assert await swarms.create("alice", groups[1]["spec"]) == groups[1]["receipt"]

        class Intake:
            async def submit(self, owner, cid, key, text):
                assert key == "swarm.message:message"
                return {"kind": "message", **await conv.accept(owner, cid, key, text)}

        swarms.chat = Intake()
        before_messages = await upgraded.call(
            lambda db: db.execute("SELECT count(*) FROM messages").fetchone()[0]
        )
        assert (
            await swarms.send(
                "alice", groups[0]["id"], {"commandKey": "message", "text": "Review old A"}
            )
            == sent
        )
        assert (
            await swarms.send(
                "alice", groups[0]["id"], {"commandKey": "message", "text": "Review old A"}
            )
            == sent
        )
        assert (
            await upgraded.call(
                lambda db: db.execute("SELECT count(*) FROM messages").fetchone()[0]
            )
            == before_messages
        )
        assert await upgraded.call(
            lambda db: row(
                db, "SELECT scope_project_id FROM swarm_groups WHERE id=?", (groups[1]["id"],)
            )
        ) == {"scope_project_id": "project-b"}
    finally:
        await upgraded.close()


@pytest.mark.parametrize("failure", ["sql", "foreign_key"])
async def test_scope_rebuild_rolls_back_every_object_and_restores_foreign_keys(
    tmp_path, monkeypatch, failure
):
    _, path, _, _ = await legacy_database(tmp_path, monkeypatch)
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("PRAGMA foreign_keys=ON")
    schema = db.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name"
    ).fetchall()
    original = facts(db)
    source = migrations.schema_file
    invalid = (
        "SELECT missing;"
        if failure == "sql"
        else "INSERT INTO swarm_posts(swarm_id,author,text,created_ms) VALUES('missing','human','must rollback',1);"
    )
    with monkeypatch.context() as changed:
        changed.setattr(
            migrations,
            "schema_file",
            lambda name: (
                source(name) + invalid if name == migrations.UPGRADES[23] else source(name)
            ),
        )
        with pytest.raises((sqlite3.OperationalError, RuntimeError)):
            migrations.upgrade_schema(db, 22)
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert not db.in_transaction
    assert db.execute("SELECT max(version) FROM schema_meta").fetchone()[0] == 22
    assert (
        db.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name"
        ).fetchall()
        == schema
    )
    assert facts(db) == original
    migrations.upgrade_schema(db, 22)
    assert db.execute("SELECT max(version) FROM schema_meta").fetchone()[0] == 23
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()


async def test_unmapped_old_create_key_cannot_create_a_replacement_team(tmp_path, monkeypatch):
    root, path, groups, _ = await legacy_database(tmp_path, monkeypatch)
    store = database_module.Database(path, root, managed=False)
    await store.open()
    try:

        def replacement(db):
            main = Conversations._new(db, "alice", "Separate canonical Main")
            db.execute(
                "INSERT INTO project_okr_conversations VALUES(?,?,?)",
                (main["id"], "alice", "project-b"),
            )
            db.execute(
                "INSERT INTO project_okr_mains VALUES(?,?,?)", ("alice", "project-b", main["id"])
            )

        await store.call(replacement, write=True)
        conv = Conversations(store)
        swarms = SwarmPlans(store, Tasks(store, conv), conv, asyncio.Event())
        from roami_agent.protocol.errors import DomainError

        with pytest.raises(DomainError, match="REQUEST_KEY_CONFLICT"):
            await swarms.create(
                "alice",
                {
                    key: value
                    for key, value in groups[1]["spec"].items()
                    if key != "mainConversationId"
                },
            )
        assert (
            await store.call(
                lambda db: db.execute("SELECT count(*) FROM swarm_groups").fetchone()[0]
            )
            == 2
        )
        assert await store.call(
            lambda db: row(
                db, "SELECT scope_project_id FROM swarm_groups WHERE id=?", (groups[1]["id"],)
            )
        ) == {"scope_project_id": None}
    finally:
        await store.close()
