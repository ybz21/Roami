"""Physical cleanup must never outrun reference publication or cross private file boundaries."""

import asyncio
import os
import threading

import pytest

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.server.configuration import Settings
from roami_agent.storage.artifact_retention import ArtifactRetention
from roami_agent.storage.artifact_store import ArtifactStore
from roami_agent.storage.database import row


@pytest.fixture
async def retention(store, monkeypatch):
    artifacts = ArtifactStore(store)
    service = ArtifactRetention(artifacts)
    future = now_ms() + 2 * 86400 * 1000
    monkeypatch.setattr("roami_agent.storage.artifact_retention.now_ms", lambda: future)
    try:
        yield artifacts, service, future
    finally:
        await service.close()
        await artifacts.close()


async def test_shared_content_lives_until_all_owners_delete_and_can_be_recreated(store, retention):
    artifacts, service, _ = retention
    first = await artifacts.put("alice", b"evidence", mime_type="text/plain")
    other = await artifacts.put("bob", b"evidence", mime_type="text/plain")
    path = artifacts._path(first["sha256"])
    await artifacts.delete("alice", first["id"])
    assert (await service.collect())["purgedBlobs"] == 0
    assert (await artifacts.read("bob", other["id"]))[1] == b"evidence"
    await artifacts.delete("bob", other["id"])
    result = await service.collect()
    assert result["purgedBlobs"] == 1 and result["reclaimedBytes"] == len(b"evidence")
    assert not path.exists()
    assert (
        await store.call(
            lambda db: db.execute(
                "SELECT COUNT(*) FROM artifacts WHERE purged_ms IS NOT NULL AND deleted_ms IS NOT NULL"
            ).fetchone()[0]
        )
        == 2
    )
    assert (await service.collect())["purgedBlobs"] == 0
    restored = await artifacts.put("alice", b"evidence", mime_type="text/plain")
    assert restored["id"] not in {first["id"], other["id"]}
    assert (await artifacts.read("alice", restored["id"]))[1] == b"evidence"
    with pytest.raises(DomainError, match="ARTIFACT_NOT_FOUND"):
        await artifacts.get("alice", first["id"])


async def test_recent_deletion_prevents_purging_shared_old_content(store, retention):
    artifacts, service, future = retention
    first = await artifacts.put("alice", b"shared", mime_type="text/plain")
    other = await artifacts.put("bob", b"shared", mime_type="text/plain")
    for owner, item in [("alice", first), ("bob", other)]:
        await artifacts.delete(owner, item["id"])
    await store.call(
        lambda db: db.execute(
            "UPDATE artifacts SET deleted_ms=? WHERE id=?", (future - 1000, other["id"])
        ),
        write=True,
    )
    result = await service.collect()
    assert result["purgedBlobs"] == 0 and artifacts._path(first["sha256"]).exists()


async def test_bounded_orphan_scan_progresses_and_leaves_unrecognized_files(retention):
    artifacts, service, future = retention
    service.batch_size = 2
    service.prefix = 0xAA
    directory = artifacts._path("aa" + "0" * 62, create=True).parent
    abandoned = []
    for index in range(5):
        path = directory / ("aa" + f"{index:062x}" + ".blob")
        path.write_bytes(b"orphan")
        abandoned.append(path)
    temporary = directory / ".artifact-deadbeef"
    temporary.write_bytes(b"partial")
    recent = directory / ".artifact-f00dbeef"
    recent.write_bytes(b"recent")
    os.utime(recent, (future / 1000, future / 1000))
    unknown = directory / "notes.txt"
    unknown.write_bytes(b"manual file")
    reclaimed = 0
    for _ in range(5):
        result = await service.collect()
        assert result["orphanFiles"] <= 2
        reclaimed += result["reclaimedBytes"]
    assert not any(path.exists() for path in abandoned) and not temporary.exists()
    assert reclaimed == 5 * len(b"orphan") + len(b"partial")
    assert recent.read_bytes() == b"recent" and unknown.read_bytes() == b"manual file"


async def test_symlinks_and_tampered_indexes_cannot_remove_external_files(
    store, retention, tmp_path
):
    artifacts, service, _ = retention
    item = await artifacts.put("alice", b"deleted", mime_type="text/plain")
    await artifacts.delete("alice", item["id"])
    blob = artifacts._path(item["sha256"])
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"preserve")
    blob.unlink()
    blob.symlink_to(outside)
    result = await service.collect()
    assert result["errors"] >= 1 and blob.is_symlink() and outside.read_bytes() == b"preserve"
    assert await store.call(
        lambda db: row(db, "SELECT purged_ms FROM artifacts WHERE id=?", (item["id"],))
    ) == {"purged_ms": None}
    await store.call(
        lambda db: db.execute("UPDATE artifacts SET path=? WHERE id=?", (str(outside), item["id"])),
        write=True,
    )
    assert (await service.collect())["purgedBlobs"] == 0
    assert outside.read_bytes() == b"preserve"


async def test_reference_publication_finishes_before_collection(store, retention, monkeypatch):
    artifacts, service, _ = retention
    old = await artifacts.put("alice", b"race", mime_type="text/plain")
    await artifacts.delete("alice", old["id"])
    started, release = threading.Event(), threading.Event()
    original = artifacts._write

    def write(body):
        result = original(body)
        started.set()
        release.wait(5)
        return result

    monkeypatch.setattr(artifacts, "_write", write)
    publishing = asyncio.create_task(artifacts.put("bob", b"race", mime_type="text/plain"))
    collecting = None
    try:
        await asyncio.to_thread(started.wait, 2)
        assert started.is_set()
        collecting = asyncio.create_task(service.collect())
        await asyncio.sleep(0.02)
        assert not collecting.done()
        release.set()
        published = await publishing
        assert (await collecting)["purgedBlobs"] == 0
        assert (await artifacts.read("bob", published["id"]))[1] == b"race"
    finally:
        release.set()
        await asyncio.gather(
            publishing, *([collecting] if collecting else []), return_exceptions=True
        )


async def test_interrupted_purge_reconciles_missing_blob_without_losing_tombstones(
    store, retention, monkeypatch
):
    artifacts, service, _ = retention
    item = await artifacts.put("alice", b"purge once", mime_type="text/plain")
    await artifacts.delete("alice", item["id"])
    original = store.call

    async def call(function, *, write=False):
        if write:
            raise DomainError("FIXTURE_COMMIT_INTERRUPTED")
        return await original(function, write=write)

    monkeypatch.setattr(store, "call", call)
    with pytest.raises(DomainError, match="FIXTURE_COMMIT_INTERRUPTED"):
        await service.collect()
    assert not artifacts._path(item["sha256"]).exists()
    monkeypatch.setattr(store, "call", original)
    result = await service.collect()
    assert result["purgedBlobs"] == 1 and result["reclaimedBytes"] == 0
    record = await store.call(
        lambda db: row(db, "SELECT * FROM artifacts WHERE id=?", (item["id"],))
    )
    assert record["purged_ms"] is not None and record["deleted_ms"] is not None


@pytest.mark.parametrize("value", [True, 0, 3599, 365 * 86400 + 1, "86400"])
async def test_invalid_retention_configuration_is_rejected(retention, tmp_path, value):
    artifacts, _, _ = retention
    with pytest.raises(DomainError, match="INVALID_ARTIFACT_RETENTION_CONFIG"):
        ArtifactRetention(artifacts, grace_seconds=value)
    config = tmp_path / "agent.toml"
    config.write_text("[artifacts]\ngc_grace_seconds=" + repr(value).lower() + "\n")
    with pytest.raises(DomainError, match="INVALID_ARTIFACT_RETENTION_CONFIG"):
        Settings.load(config)


async def test_cancelled_unpublished_write_is_reclaimed_after_it_finishes(retention, monkeypatch):
    artifacts, service, _ = retention
    started, release = threading.Event(), threading.Event()
    original = artifacts._write

    def write(body):
        result = original(body)
        started.set()
        release.wait(5)
        return result

    monkeypatch.setattr(artifacts, "_write", write)
    pending = asyncio.create_task(artifacts.put("alice", b"unpublished", mime_type="text/plain"))
    try:
        await asyncio.to_thread(started.wait, 2)
        assert started.is_set()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        release.set()
        await asyncio.gather(*(asyncio.shield(future) for future in tuple(artifacts.pending)))
        blobs = list((artifacts.data_root / "agent-artifacts/blobs").rglob("*.blob"))
        assert len(blobs) == 1
        service.prefix = int(blobs[0].name[:2], 16)
        assert (await service.collect())["orphanFiles"] == 1
        assert not blobs[0].exists() and await artifacts.list("alice") == []
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


async def test_schema_five_upgrades_without_expiring_live_artifacts(tmp_path, monkeypatch):
    from roami_agent.storage import migrations
    from roami_agent.storage.database import Database

    root = tmp_path / "upgrade"
    path = root / "database/agents/runtime.db"
    with monkeypatch.context() as context:
        context.setattr(migrations, "SCHEMA_VERSION", 5)
        database = Database(path, root, managed=False)
        await database.open()
        artifacts = ArtifactStore(database)
        try:
            original = await artifacts.put("alice", b"keep across upgrade", mime_type="text/plain")
        finally:
            await artifacts.close()
            await database.close()
    database = Database(path, root, managed=False)
    await database.open()
    artifacts = ArtifactStore(database)
    retention = ArtifactRetention(artifacts)
    try:
        assert (await artifacts.read("alice", original["id"]))[1] == b"keep across upgrade"
        assert (await retention.collect())["purgedBlobs"] == 0
        record = await database.call(
            lambda db: row(db, "SELECT * FROM artifacts WHERE id=?", (original["id"],))
        )
        assert record["purged_ms"] is None and record["deleted_ms"] is None
    finally:
        await retention.close()
        await artifacts.close()
        await database.close()


async def test_unsafe_blob_does_not_starve_later_indexed_cleanup(retention, tmp_path):
    artifacts, service, _ = retention
    service.batch_size = 1
    items = [
        await artifacts.put("alice", body, mime_type="text/plain")
        for body in [b"first candidate", b"second candidate"]
    ]
    unsafe, healthy = sorted(items, key=lambda item: item["sha256"])
    for item in items:
        await artifacts.delete("alice", item["id"])
    outside = tmp_path / "preserve.txt"
    outside.write_bytes(b"preserve")
    unsafe_path = artifacts._path(unsafe["sha256"])
    unsafe_path.unlink()
    unsafe_path.symlink_to(outside)
    assert (await service.collect())["errors"] >= 1
    assert (await service.collect())["purgedBlobs"] == 1
    assert not artifacts._path(healthy["sha256"]).exists()
    assert outside.read_bytes() == b"preserve" and unsafe_path.is_symlink()


async def test_slow_physical_cleanup_does_not_block_main_chat(store, monkeypatch):
    from roami_agent.app import Runtime
    from roami_agent.protocol.models import ModelEvent

    class Model:
        model = "retention-latency-fixture"

        async def stream(self, messages, tools):
            yield ModelEvent("text", "responsive")

    runtime = Runtime(store, Model())
    future = now_ms() + 2 * 86400 * 1000
    monkeypatch.setattr("roami_agent.storage.artifact_retention.now_ms", lambda: future)
    item = await runtime.artifacts.put("alice", b"remove later", mime_type="text/plain")
    await runtime.artifacts.delete("alice", item["id"])
    started, release = threading.Event(), threading.Event()
    original = runtime.artifact_retention._unlink

    def unlink(*args):
        started.set()
        release.wait(5)
        return original(*args)

    monkeypatch.setattr(runtime.artifact_retention, "_unlink", unlink)
    await runtime.start()
    collecting = asyncio.create_task(runtime.artifact_retention.collect())
    try:
        await asyncio.to_thread(started.wait, 2)
        assert started.is_set()
        conversation = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", conversation["id"], "quick", "hello")
        async with asyncio.timeout(1):
            while True:
                turn = await store.call(
                    lambda db: row(db, "SELECT state FROM turns WHERE id=?", (receipt["turnId"],))
                )
                if turn["state"] == "completed":
                    break
                await asyncio.sleep(0.01)
        assert not collecting.done() and not release.is_set()
    finally:
        release.set()
        await asyncio.gather(collecting, return_exceptions=True)
        await runtime.close()
