"""An upgrade preserves original evidence and queues, rather than models, old sources."""

import sqlite3

import pytest

from roami_agent.conversation.transcript import Conversations
from roami_agent.storage import database as database_module
from roami_agent.storage import migrations
from roami_agent.storage.database import Database
from roami_agent.storage.transcript_repository import message


async def test_schema_29_upgrade_is_atomic_and_backfills_stable_text_only(tmp_path, monkeypatch):
    path = tmp_path / "runtime.db"
    with monkeypatch.context() as old:
        old.setattr(migrations, "SCHEMA_VERSION", 28)
        old.setattr(database_module, "SCHEMA_VERSION", 28)
        database = Database(path, tmp_path, managed=False)
        await database.open()
        try:
            c = await Conversations(database).create("alice")
            mids = await database.call(
                lambda db: [
                    message(
                        db, c["id"], c["active_branch_id"], "user", {"text": "original retained"}
                    ),
                    message(
                        db,
                        c["id"],
                        c["active_branch_id"],
                        "assistant",
                        {"text": "in progress"},
                        status="streaming",
                    ),
                    message(
                        db,
                        c["id"],
                        c["active_branch_id"],
                        "assistant",
                        {"text": "stable interrupted evidence"},
                        status="interrupted",
                    ),
                ],
                write=True,
            )
            before = await database.call(
                lambda db: [
                    tuple(value) for value in db.execute("SELECT * FROM messages ORDER BY rowid")
                ]
            )
        finally:
            await database.close()
    db = sqlite3.connect(path, isolation_level=None)
    try:
        source = migrations.schema_file
        with monkeypatch.context() as broken:
            broken.setattr(
                migrations,
                "schema_file",
                lambda name: source(name) + "\nSELECT missing_context_upgrade_fixture;",
            )
            with pytest.raises(sqlite3.OperationalError, match="missing_context_upgrade_fixture"):
                migrations.upgrade_schema(db, 28)
        assert db.execute("SELECT max(version) FROM schema_meta").fetchone()[0] == 28
        assert (
            db.execute("SELECT 1 FROM sqlite_master WHERE name='context_briefs'").fetchone() is None
        )
        migrations.upgrade_schema(db, 28)
        assert (
            db.execute("SELECT max(version) FROM schema_meta").fetchone()[0]
            == migrations.SCHEMA_VERSION
        )
        assert {
            value[0] for value in db.execute("SELECT message_id FROM conversation_search_pending")
        } == {mids[0], mids[2]}
        assert db.execute("SELECT * FROM messages ORDER BY rowid").fetchall() == before
        assert db.execute("SELECT count(*) FROM context_briefs").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM period_summaries").fetchone()[0] == 0
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        db.close()
