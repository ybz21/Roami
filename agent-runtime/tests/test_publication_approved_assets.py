import json

import pytest
from test_publication_review import review_fixture
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture

from roami_agent.dispatch.publication_review import PublicationReview
from roami_agent.protocol.errors import DomainError
from roami_agent.publication.approved_assets import approved_assets
from roami_agent.storage.database import row
from roami_agent.storage.publication_versions import freeze_version

coordination = coordination_fixture
delegated_team = delegated_team_fixture


async def prepared(value):
    runtime, binding, old = await review_fixture(value)
    version = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM swarm_publication_versions WHERE id=?", (old["versionId"],)
        )
    )
    manifest = json.loads(version["manifest_json"])
    scope = manifest["author"]
    frozen = await runtime.db.call(
        lambda db: freeze_version(
            db,
            binding,
            version["item_id"],
            scope,
            manifest["artifacts"],
            manifest["content"],
            account_identity="12345",
        ),
        write=True,
    )
    review = await PublicationReview(runtime.db, runtime.artifacts, runtime.reply_review).decide(
        binding, frozen["versionId"], "approved", "Read the exact frozen body"
    )
    return runtime, binding, scope, frozen, review


async def test_approved_snapshot_does_not_require_producer_to_remain_on_old_revision(coordination):
    runtime, _binding, scope, frozen, review = await prepared(coordination)
    before = await runtime.db.call(
        lambda db: approved_assets(
            db, "alice", scope, frozen["versionId"], review["reviewId"], "x", "12345"
        )
    )
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE tasks SET revision=revision+1,state='queued' WHERE id=?", (scope["taskId"],)
        ),
        write=True,
    )
    after = await runtime.db.call(
        lambda db: approved_assets(
            db, "alice", scope, frozen["versionId"], review["reviewId"], "x", "12345"
        )
    )
    assert before == after and after["publicationAuthorized"] is False
    assert after["manifest"]["author"]["revision"] == 1


@pytest.mark.parametrize(
    "fault", ["owner", "project", "account", "review", "deleted_asset", "deleted_review", "revoked"]
)
async def test_history_does_not_override_scope_or_forgotten_approval(coordination, fault):
    runtime, binding, scope, frozen, review = await prepared(coordination)
    owner, account, review_id = "alice", "12345", review["reviewId"]
    if fault == "owner":
        owner = "bob"
    elif fault == "project":
        scope["projectId"] = "other"
    elif fault == "account":
        account = "999"
    elif fault == "review":
        review_id = "unapproved"
    elif fault == "deleted_asset":
        artifact = await runtime.db.call(
            lambda db: row(
                db,
                "SELECT id FROM artifacts WHERE task_id=? AND name='post.md'",
                (scope["taskId"],),
            )
        )
        await runtime.artifacts.delete("alice", artifact["id"])
    elif fault == "deleted_review":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE messages SET deleted_ms=1 WHERE id=?", (binding["assistantMessageId"],)
            ),
            write=True,
        )
    else:
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE swarm_goal_delegations SET revoked_ms=1,revoked_by_message_id=source_message_id WHERE id=?",
                (scope["delegationId"],),
            ),
            write=True,
        )
    with pytest.raises(DomainError):
        await runtime.db.call(
            lambda db: approved_assets(
                db, owner, scope, frozen["versionId"], review_id, "x", account
            )
        )


async def test_content_only_approval_does_not_select_a_publishing_account(coordination):
    runtime, binding, frozen = await review_fixture(coordination)
    version = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT manifest_json FROM swarm_publication_versions WHERE id=?",
            (frozen["versionId"],),
        )
    )
    scope = json.loads(version["manifest_json"])["author"]
    review = await PublicationReview(runtime.db, runtime.artifacts, runtime.reply_review).decide(
        binding, frozen["versionId"], "approved", "Content checked; account not selected"
    )
    with pytest.raises(DomainError, match="PUBLICATION_ACCOUNT_SCOPE_CONFLICT"):
        await runtime.db.call(
            lambda db: approved_assets(
                db, "alice", scope, frozen["versionId"], review["reviewId"], "x", "12345"
            )
        )


async def test_a_new_draft_version_blocks_consumption_of_old_approval(coordination):
    runtime, binding, scope, frozen, review = await prepared(coordination)
    old = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM swarm_publication_versions WHERE id=?", (frozen["versionId"],)
        )
    )
    manifest = json.loads(old["manifest_json"])
    await runtime.db.call(
        lambda db: freeze_version(
            db,
            binding,
            old["item_id"],
            scope,
            manifest["artifacts"],
            manifest["content"],
            account_identity="999",
        ),
        write=True,
    )
    with pytest.raises(DomainError, match="PUBLICATION_VERSION_SUPERSEDED"):
        await runtime.db.call(
            lambda db: approved_assets(
                db, "alice", scope, frozen["versionId"], review["reviewId"], "x", "12345"
            )
        )
