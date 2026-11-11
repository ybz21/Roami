import sqlite3

import pytest
from test_runtime import ConversationModel

import roami_agent.storage.database as database_module
from roami_agent.app import Runtime
from roami_agent.storage import migrations
from roami_agent.storage.database import Database


async def test_schema26_history_is_retained_by_current_upgrade(tmp_path, monkeypatch):
    data = tmp_path / "data"
    path = data / "runtime.db"
    with monkeypatch.context() as patch:
        patch.setattr(database_module, "SCHEMA_VERSION", 26)
        patch.setattr(migrations, "SCHEMA_VERSION", 26)
        db = Database(path, data, managed=False)
        await db.open()
        runtime = Runtime(db, ConversationModel())
        try:
            conversation = await runtime.conversations.create("alice")
            await runtime.conversations.accept(
                "alice", conversation["id"], "old-goal", "Keep this original history"
            )
            before = await db.call(
                lambda c: [tuple(r) for r in c.execute("SELECT * FROM messages ORDER BY rowid")]
            )
            assert (
                await db.call(
                    lambda c: c.execute("SELECT MAX(version) FROM schema_meta").fetchone()[0]
                )
                == 26
            )
        finally:
            await runtime.close()
            await db.close()
    reopened = Database(path, data, managed=False)
    await reopened.open()
    try:
        assert (
            await reopened.call(
                lambda c: c.execute("SELECT MAX(version) FROM schema_meta").fetchone()[0]
            )
            == migrations.SCHEMA_VERSION
        )
        assert before == await reopened.call(
            lambda c: [tuple(r) for r in c.execute("SELECT * FROM messages ORDER BY rowid")]
        )
        assert (
            await reopened.call(lambda c: c.execute("PRAGMA integrity_check").fetchone()[0]) == "ok"
        )
        assert await reopened.call(lambda c: c.execute("PRAGMA foreign_key_check").fetchall()) == []
        for table in [
            "swarm_publication_items",
            "swarm_publication_versions",
            "swarm_publication_reviews",
            "swarm_publication_source_files",
        ]:
            assert (
                await reopened.call(
                    lambda c, table=table: c.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                )
                == 0
            )
    finally:
        await reopened.close()
    with sqlite3.connect(path) as db:
        assert (
            db.execute("SELECT MAX(version) FROM schema_meta").fetchone()[0]
            == migrations.SCHEMA_VERSION
        )


def test_schema27_failure_rolls_back_without_publication_grants(tmp_path, monkeypatch):

    path = tmp_path / "runtime.db"
    with sqlite3.connect(path, isolation_level=None) as db:
        db.execute("PRAGMA foreign_keys=ON")
        with monkeypatch.context() as old:
            old.setattr(migrations, "SCHEMA_VERSION", 26)
            db.executescript(migrations.schema_file("0001_initial.sql"))
            migrations.upgrade_schema(db, 1)
        before = db.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
        source = migrations.schema_file
        with monkeypatch.context() as broken:
            broken.setattr(
                migrations,
                "schema_file",
                lambda name: (
                    source(name) + "\nSELECT missing_publication_source;"
                    if name == migrations.UPGRADES[27]
                    else source(name)
                ),
            )
            with pytest.raises(sqlite3.OperationalError, match="missing_publication_source"):
                migrations.upgrade_schema(db, 26)
        assert not db.in_transaction
        assert db.execute("SELECT max(version) FROM schema_meta").fetchone()[0] == 26
        assert (
            db.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
            == before
        )
        migrations.upgrade_schema(db, 26)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert (
            db.execute("SELECT max(version) FROM schema_meta").fetchone()[0]
            == migrations.SCHEMA_VERSION
        )
