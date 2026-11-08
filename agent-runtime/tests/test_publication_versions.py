import json
import sqlite3

import pytest
from test_publication_author_scope import scope_fixture
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.publication_versions import create_item, freeze_version

coordination = coordination_fixture
delegated_team = delegated_team_fixture


async def prepared(fixture):
    runtime, binding, scope = await scope_fixture(fixture)
    item = await runtime.db.call(
        lambda db: create_item(db, binding, scope, "feature-agent-one", "x"), write=True
    )
    artifact = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT id,sha256 FROM artifacts WHERE task_id=? AND name='post.md'",
            (scope["taskId"],),
        )
    )
    return runtime, binding, scope, item, [artifact]


async def test_original_business_item_and_exact_version_survive_retry(coordination):
    runtime, binding, scope, item, artifacts = await prepared(coordination)
    again = await runtime.db.call(
        lambda db: create_item(db, binding, scope, "feature-agent-one", "x"), write=True
    )
    assert again == item and item["publicationAuthorized"] is False
    content = {"body": artifacts[0]["id"]}
    first = await runtime.db.call(
        lambda db: freeze_version(db, binding, item["id"], scope, artifacts, content), write=True
    )
    second = await runtime.db.call(
        lambda db: freeze_version(db, binding, item["id"], scope, artifacts, content), write=True
    )
    assert first == second and first["publicationAuthorized"] is False
    saved = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM swarm_publication_versions WHERE id=?", (first["versionId"],)
        )
    )
    assert json.loads(saved["manifest_json"])["author"]["runId"] == scope["runId"]
    for table, ident in [
        ("swarm_publication_items", item["id"]),
        ("swarm_publication_versions", first["versionId"]),
    ]:
        with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE"):
            await runtime.db.call(
                lambda db, table=table, ident=ident: db.execute(
                    "UPDATE " + table + " SET created_ms=0 WHERE id=?", (ident,)
                ),
                write=True,
            )


@pytest.mark.parametrize("fault", ["owner", "project", "run", "content", "unreferenced", "account"])
async def test_wrong_scope_or_unfrozen_content_is_rejected(coordination, fault):
    runtime, binding, scope, item, artifacts = await prepared(coordination)
    content = {"body": artifacts[0]["id"]}
    account = None
    if fault == "owner":
        binding["owner"] = "other"
    elif fault == "project":
        scope["projectId"] = "other"
    elif fault == "run":
        scope["runId"] = "other"
    elif fault == "content":
        content = {"body": "new unfrozen text"}
    elif fault == "unreferenced":
        content = {"images": [artifacts[0]["id"]]}
    else:
        account = "credential-or-handle"
    with pytest.raises(DomainError):
        await runtime.db.call(
            lambda db: freeze_version(
                db, binding, item["id"], scope, artifacts, content, account_identity=account
            ),
            write=True,
        )
