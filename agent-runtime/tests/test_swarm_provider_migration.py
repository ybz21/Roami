"""Existing executor generations must not regress during the provider-binding upgrade."""

import json

from roami_agent.conversation.transcript import Conversations
from roami_agent.storage import database as database_module
from roami_agent.storage import migrations
from roami_agent.storage.database import Database, row
from roami_okr.main import open_main


async def test_schema30_provider_upgrade_preserves_existing_generation(tmp_path, monkeypatch):
    path = tmp_path / "runtime.db"
    with monkeypatch.context() as old:
        old.setattr(migrations, "SCHEMA_VERSION", 30)
        old.setattr(database_module, "SCHEMA_VERSION", 30)
        database = Database(path, tmp_path, managed=False)
        await database.open()
        main = await open_main(Conversations(database), "alice", "project-a")

        def seed(db):
            db.execute(
                "INSERT INTO swarm_groups(id,owner_id,name,conversation_id,goal,target_json,scope_project_id,created_ms,updated_ms) VALUES('swarm','alice','Team',?,'Read',?,'project-a',1,1)",
                (main["id"], json.dumps({"kind": "project", "projectId": "project-a"})),
            )
            for ident, generation in [("current", 2), ("history", 4)]:
                db.execute(
                    "INSERT INTO swarm_work_items(id,swarm_id,member_name,executor,title,goal,acceptance,model,execution_generation) VALUES(?,'swarm',?,'claude','Read','Read','Verify','free',?)",
                    (ident, ident, generation),
                )
            db.execute(
                "INSERT INTO swarm_members(id,swarm_id,name,executor,duty,created_ms,model) VALUES('member','swarm','Research','claude','Retain references',1,'free')"
            )
            db.execute("INSERT INTO swarm_member_work VALUES('member','current')")
            db.execute("INSERT INTO swarm_member_work VALUES('member','history')")
            db.execute("UPDATE swarm_members SET current_work_id='current' WHERE id='member'")
            return row(db, "SELECT * FROM swarm_members WHERE id='member'")

        before = await database.call(seed, write=True)
        await database.close()
    upgraded = Database(path, tmp_path, managed=False)
    await upgraded.open()
    try:
        current = await upgraded.call(
            lambda db: row(db, "SELECT * FROM swarm_members WHERE id='member'")
        )
        assert current.pop("execution_generation") == 4
        assert current.pop("retired_ms") is None
        assert current == before
        assert (
            await upgraded.call(
                lambda db: db.execute(
                    "SELECT execution_generation FROM swarm_work_items WHERE id='current'"
                ).fetchone()[0]
            )
            == 2
        )
        assert (
            await upgraded.call(
                lambda db: db.execute(
                    "SELECT count(*) FROM swarm_member_provider_generations"
                ).fetchone()[0]
            )
            == 0
        )
        assert (
            await upgraded.call(lambda db: db.execute("PRAGMA foreign_key_check").fetchall()) == []
        )
    finally:
        await upgraded.close()
