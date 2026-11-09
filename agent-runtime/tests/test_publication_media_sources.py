import pytest
from test_publication_media_inspection import Decoder
from test_publication_media_scope import media_fixture
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture

from roami_agent.dispatch.publication_media import PublicationMedia
from roami_agent.protocol.errors import DomainError

coordination = coordination_fixture
delegated_team = delegated_team_fixture


async def test_retained_contact_sheets_are_real_owned_artifacts_not_author_claims(coordination):
    runtime, binding, _, version, media, _ = await media_fixture(coordination)
    service = PublicationMedia(runtime.db, runtime.artifacts, Decoder())
    value = await service.retain(binding, version["versionId"], media["id"])
    again = await service.retain(binding, version["versionId"], media["id"])
    assert value == again and value["publicationAuthorized"] is False
    assert len(value["images"]) == 3 and value["audio"] is None
    for image in value["images"]:
        reference, body = await runtime.artifacts.read("alice", image["id"])
        assert body.startswith(b"\x89PNG\r\n\x1a\n")
        assert reference["metadata"]["kind"] == "publication_media"
    await runtime.artifacts.delete("alice", media["id"])
    for ref in [value["report"], *value["images"]]:
        with pytest.raises(DomainError, match="PUBLICATION_MEDIA_SOURCE_UNAVAILABLE"):
            await runtime.artifacts.read("alice", ref["id"])


async def derived_fixture(fixture):
    runtime, _, _, version, media, _ = await media_fixture(fixture)
    metadata = {
        "kind": "publication_media",
        "mediaSource": {
            "versionId": version["versionId"],
            "artifactId": media["id"],
            "sha256": media["sha256"],
        },
    }
    derived = await runtime.artifacts.put(
        "alice",
        b"Derived final-track transcript",
        name="transcript.txt",
        mime_type="text/plain",
        metadata=metadata,
    )
    return runtime, media, derived, metadata


async def test_derived_source_is_required_before_registration(coordination):
    runtime, _, _, metadata = await derived_fixture(coordination)
    metadata["mediaSource"]["sha256"] = "0" * 64
    with pytest.raises(DomainError, match="PUBLICATION_MEDIA_SOURCE_UNAVAILABLE"):
        await runtime.artifacts.put(
            "alice",
            b"Invalid derived result",
            name="bad.txt",
            mime_type="text/plain",
            metadata=metadata,
        )


@pytest.mark.parametrize(
    "fault", ["deleted", "purged", "forgotten", "derived-forgotten", "derived-purged"]
)
@pytest.mark.parametrize("operation", ["get", "read", "read_page", "verified_path"])
async def test_normal_artifact_reads_cannot_bypass_removed_media_source(
    coordination, fault, operation
):
    runtime, media, derived, _ = await derived_fixture(coordination)
    assert (await runtime.artifacts.read("alice", derived["id"]))[
        1
    ] == b"Derived final-track transcript"
    target = derived if fault.startswith("derived-") else media
    if fault.endswith("forgotten"):
        sql, args = (
            "INSERT INTO memory_tombstones VALUES(?,?,?,1)",
            ("alice", target["sha256"], "forgotten-source"),
        )
    else:
        column = "deleted_ms" if fault == "deleted" else "purged_ms"
        sql, args = "UPDATE artifacts SET " + column + "=1 WHERE id=?", (target["id"],)
    await runtime.db.call(lambda db: db.execute(sql, args), write=True)
    invoke = getattr(runtime.artifacts, operation)
    args = (
        ("alice", derived["id"], 0, 100) if operation == "read_page" else ("alice", derived["id"])
    )
    with pytest.raises(DomainError, match="PUBLICATION_MEDIA_SOURCE_UNAVAILABLE"):
        await invoke(*args)


async def test_removal_during_disk_io_discards_the_loaded_transcript(coordination, monkeypatch):
    runtime, media, derived, _ = await derived_fixture(coordination)
    original = runtime.artifacts._io

    async def removing_io(function, *args):
        value = await original(function, *args)
        await runtime.db.call(
            lambda db: db.execute("UPDATE artifacts SET deleted_ms=1 WHERE id=?", (media["id"],)),
            write=True,
        )
        return value

    monkeypatch.setattr(runtime.artifacts, "_io", removing_io)
    with pytest.raises(DomainError, match="PUBLICATION_MEDIA_SOURCE_UNAVAILABLE"):
        await runtime.artifacts.read("alice", derived["id"])
