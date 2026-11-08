"""Result observation storage upgrades without granting or replaying old work."""

import sqlite3

import pytest
from test_swarm_scope_migration import facts, legacy_database

from roami_agent.storage import migrations


async def test_schema26_rolls_back_and_preserves_all_old_facts_on_retry(tmp_path, monkeypatch):
    _, path, _, _ = await legacy_database(tmp_path, monkeypatch)
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with monkeypatch.context() as old:
            old.setattr(migrations, "SCHEMA_VERSION", 25)
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
                    source(name)
                    + (
                        "\nSELECT missing_observation_fixture;"
                        if name == migrations.UPGRADES[26]
                        else ""
                    )
                ),
            )
            with pytest.raises(sqlite3.OperationalError, match="missing_observation_fixture"):
                migrations.upgrade_schema(db, 25)
        assert db.execute("SELECT max(version) FROM schema_meta").fetchone()[0] == 25
        assert facts(db) == original
        assert (
            db.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name"
            ).fetchall()
            == objects
        )
        migrations.upgrade_schema(db, 25)
        current = facts(db)
        assert current.pop("swarm_coordination_results") == []
        assert current.pop("swarm_result_observations") == []
        for table in (
            "swarm_publication_items",
            "swarm_publication_versions",
            "swarm_publication_reviews",
            "swarm_publication_source_files",
        ):
            assert current.pop(table) == []
        assert current == original and db.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        db.close()
