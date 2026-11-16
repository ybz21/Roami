import sqlite3

import pytest
from test_swarm_scope_migration import facts, legacy_database
from test_web_pages import seed_messages

from roami_agent.conversation.pages import activity_summaries
from roami_agent.storage import migrations
from roami_agent.storage.database import event


async def test_activity_index_preserves_latest_updates_and_uses_selected_anchors(store):
    conversation, mids = await seed_messages(store, 2)
    cid = conversation["id"]

    def check(db):
        for i in range(50):
            event(db, cid, "message.delta", {"text": "old output" * 2000})
        for ident, anchor, state, kind in (
            ("tool:a", mids[0], "running", "tool.started"),
            ("tool:b", mids[1], "succeeded", "tool.completed"),
            ("tool:a", mids[0], "succeeded", "future.activity"),
        ):
            event(
                db,
                cid,
                kind,
                {
                    "activity": {
                        "id": ident,
                        "anchorMessageId": anchor,
                        "startedMs": 1,
                        "state": state,
                        "preview": {"input": "private tool input"},
                        "routingDecision": {"private": True},
                    }
                },
            )
        selected = [{"id": mids[0]}]
        db.execute("DROP INDEX events_activity_anchor")
        before = activity_summaries(db, cid, selected)
        db.execute(migrations.schema_file(migrations.UPGRADES[28]))
        queries = []
        db.set_trace_callback(queries.append)
        try:
            after = activity_summaries(db, cid, selected)
        finally:
            db.set_trace_callback(None)
        assert (
            before
            == after
            == [{"id": "tool:a", "anchorMessageId": mids[0], "startedMs": 1, "state": "succeeded"}]
        )
        query = next(sql for sql in queries if "SELECT MAX(id)" in sql)
        plan = db.execute("EXPLAIN QUERY PLAN " + query).fetchall()
        assert any("events_activity_anchor" in item[3] for item in plan)

    await store.call(check, write=True)


async def test_activity_index_upgrade_rolls_back_and_preserves_legacy_facts(tmp_path, monkeypatch):
    _, path, _, _ = await legacy_database(tmp_path, monkeypatch)
    db = sqlite3.connect(path, isolation_level=None)
    try:
        with monkeypatch.context() as old:
            old.setattr(migrations, "SCHEMA_VERSION", 27)
            migrations.upgrade_schema(db, 22)
        before = facts(db)
        source = migrations.schema_file
        with monkeypatch.context() as failure:
            failure.setattr(
                migrations,
                "schema_file",
                lambda name: source(name) + "\nSELECT missing_activity_index_fixture;",
            )
            with pytest.raises(sqlite3.OperationalError, match="missing_activity_index_fixture"):
                migrations.upgrade_schema(db, 27)
        assert db.execute("SELECT max(version) FROM schema_meta").fetchone()[0] == 27
        assert (
            db.execute("SELECT 1 FROM sqlite_master WHERE name='events_activity_anchor'").fetchone()
            is None
        )
        assert facts(db) == before
        migrations.upgrade_schema(db, 27)
        assert db.execute("SELECT max(version) FROM schema_meta").fetchone()[0] == 28
        assert facts(db) == before
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        db.close()
