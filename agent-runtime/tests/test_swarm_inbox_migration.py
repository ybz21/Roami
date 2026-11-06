"""Inbox schema adds no invented history and rolls back all partial DDL."""

import sqlite3

import pytest
from test_swarm_scope_migration import facts, legacy_database

from roami_agent.storage import migrations


async def test_schema23_inbox_upgrade_preserves_every_existing_fact(tmp_path, monkeypatch):
    _, path, _, _ = await legacy_database(tmp_path, monkeypatch)
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with monkeypatch.context() as previous:
            previous.setattr(migrations, "SCHEMA_VERSION", 23)
            migrations.upgrade_schema(db, 22)
        original = facts(db)
        original_schema = db.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name"
        ).fetchall()
        source = migrations.schema_file
        with monkeypatch.context() as failure:
            failure.setattr(
                migrations,
                "schema_file",
                lambda name: (
                    source(name) + "\nSELECT injected_missing;"
                    if name == migrations.UPGRADES[24]
                    else source(name)
                ),
            )
            with pytest.raises(sqlite3.OperationalError, match="injected_missing"):
                migrations.upgrade_schema(db, 23)
        assert db.execute("SELECT max(version) FROM schema_meta").fetchone()[0] == 23
        assert not db.in_transaction
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert (
            db.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name"
            ).fetchall()
            == original_schema
        )
        assert facts(db) == original
        migrations.upgrade_schema(db, 23)
        current = facts(db)
        assert current.pop("swarm_post_routes") == []
        assert current.pop("swarm_inbox") == []
        assert current == original
        assert db.execute("SELECT max(version) FROM schema_meta").fetchone()[0] == 24
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        db.close()
