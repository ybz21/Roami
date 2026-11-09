import json

import pytest
from test_publication_media_inspection import Decoder
from test_publication_versions import prepared
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture

from roami_agent.dispatch.publication_media import PublicationMedia
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.publication_versions import freeze_version

coordination = coordination_fixture
delegated_team = delegated_team_fixture


async def media_fixture(fixture, *, account=None, source_mime="video/mp4"):
    runtime, binding, scope, item, artifacts = await prepared(fixture)
    media = await runtime.artifacts.put(
        "alice",
        b"frozen video bytes",
        name="clip.mp4",
        mime_type=source_mime,
        task_id=scope["taskId"],
        metadata={"kind": "deliverable", "runId": scope["runId"], "provisional": False},
    )

    def retain(db):
        value = json.loads(
            db.execute(
                "SELECT result_json FROM task_attempts WHERE id=?", (scope["runId"],)
            ).fetchone()[0]
        )
        value["artifactRefs"].append(media)
        db.execute(
            "UPDATE task_attempts SET result_json=? WHERE id=?", (json.dumps(value), scope["runId"])
        )

    await runtime.db.call(retain, write=True)
    version = await runtime.db.call(
        lambda db: freeze_version(
            db,
            binding,
            item["id"],
            scope,
            [*artifacts, media],
            {
                "body": artifacts[0]["id"],
                "audio" if source_mime.startswith("audio/") else "video": media["id"],
            },
            account_identity=account,
        ),
        write=True,
    )
    return runtime, binding, scope, version, media, artifacts[0]


async def test_original_version_decodes_without_issuing_an_approval(coordination):
    runtime, binding, _, version, media, _ = await media_fixture(coordination)
    decoded = await PublicationMedia(runtime.db, runtime.artifacts, Decoder()).inspect(
        binding, version["versionId"], media["id"]
    )
    assert len(decoded.sheets) == 3
    assert decoded.report["sourceSha256"] == media["sha256"]
    assert decoded.report["publicationAuthorized"] is False
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_publication_reviews").fetchone()[0]
        )
        == 0
    )


@pytest.mark.parametrize(
    "fault",
    [
        "home",
        "lease",
        "body",
        "revoked_during_decode",
        "advanced_during_decode",
        "deleted_during_decode",
    ],
)
async def test_cross_project_and_mid_decode_changes_discard_media(coordination, fault):
    runtime, binding, scope, version, media, body = await media_fixture(coordination)
    decoder = Decoder()
    selected = media["id"]
    if fault == "home":
        binding["conversation"] = (await runtime.conversations.create("alice"))["id"]
    elif fault == "lease":
        binding["leaseEpoch"] += 1
    elif fault == "body":
        selected = body["id"]
    else:
        original = decoder.probe

        async def revoke(path, mime):
            if fault == "revoked_during_decode":
                sql, args = (
                    "UPDATE swarm_goal_delegations SET revoked_ms=1,revoked_by_message_id=source_message_id WHERE id=?",
                    (scope["delegationId"],),
                )
            elif fault == "advanced_during_decode":
                sql, args = "UPDATE tasks SET revision=revision+1 WHERE id=?", (scope["taskId"],)
            else:
                sql, args = "UPDATE artifacts SET deleted_ms=1 WHERE id=?", (media["id"],)
            await runtime.db.call(lambda db: db.execute(sql, args), write=True)
            return await original(path, mime)

        decoder.probe = revoke
    with pytest.raises(DomainError):
        await PublicationMedia(runtime.db, runtime.artifacts, decoder).inspect(
            binding, version["versionId"], selected
        )
    if not fault.endswith("during_decode"):
        assert decoder.positions == []
