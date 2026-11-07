"""Adding delegation storage must not manufacture authority for old teams."""

import sqlite3

import pytest
from test_swarm_scope_migration import facts, legacy_database

from roami_agent.storage import migrations


async def test_schema25_failure_and_retry_preserve_old_data_without_legacy_grants(
    tmp_path, monkeypatch
):
    _, path, _, _ = await legacy_database(tmp_path, monkeypatch)
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with monkeypatch.context() as previous:
            previous.setattr(migrations, "SCHEMA_VERSION", 24)
            migrations.upgrade_schema(db, 22)
        original = facts(db)
        objects = db.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name"
        ).fetchall()
        source = migrations.schema_file
        with monkeypatch.context() as failure:
            failure.setattr(
                migrations,
                "schema_file",
                lambda name: (
                    source(name) + "\nSELECT missing_delegation_source;"
                    if name == migrations.UPGRADES[25]
                    else source(name)
                ),
            )
            with pytest.raises(sqlite3.OperationalError, match="missing_delegation_source"):
                migrations.upgrade_schema(db, 24)
        assert db.execute("SELECT max(version) FROM schema_meta").fetchone()[0] == 24
        assert not db.in_transaction
        assert (
            db.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name"
            ).fetchall()
            == objects
        )
        assert facts(db) == original
        migrations.upgrade_schema(db, 24)
        current = facts(db)
        assert current.pop("swarm_goal_delegations") == []
        assert current.pop("swarm_coordination_batches") == []
        assert current.pop("swarm_coordination_inputs") == []
        assert current == original
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        db.close()
