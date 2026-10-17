"""Evidence stays owner-scoped, immutable and durable before a reference is published."""

import asyncio
import fcntl
import os
import sqlite3
import threading

import httpx
import pytest

from roami_agent.app import Runtime
from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.tasks import Tasks
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.http import create_app
from roami_agent.storage import migrations
from roami_agent.storage.artifact_store import ArtifactStore
from roami_agent.storage.database import Database, row


@pytest.fixture
async def artifacts(store):
    service = ArtifactStore(store)
    yield service
    await service.close()


class Model:
    model = "artifact-fixture"

    async def stream(self, messages, tools):
        yield ModelEvent("text", "unused")


async def test_size_and_metadata_validation_happen_before_creating_files(store):
    service = ArtifactStore(store, max_bytes=4)
    try:
        with pytest.raises(DomainError, match="ARTIFACT_SIZE_LIMIT"):
            await service.put("alice", b"12345", mime_type="text/plain")
        with pytest.raises(DomainError, match="INVALID_ARTIFACT_METADATA"):
            await service.put(
                "alice", b"data", mime_type="text/plain", metadata={"scale": float("nan")}
            )
        with pytest.raises(DomainError, match="INVALID_ARTIFACT_NAME"):
            await service.put("alice", b"data", mime_type="text/plain", name="../outside")
        assert not (store.data_root / "agent-artifacts").exists()
    finally:
        await service.close()


async def test_shared_bytes_have_separate_owners_and_deleted_references_do_not_resurrect(
    artifacts, store
):
    first = await artifacts.put("alice", b"evidence", mime_type="text/plain", name="report.txt")
    retry = await artifacts.put("alice", b"evidence", mime_type="text/plain", name="report.txt")
    other = await artifacts.put("bob", b"evidence", mime_type="text/plain", name="report.txt")
    assert first["id"] == retry["id"] and other["id"] != first["id"]
    assert len(list((store.data_root / "agent-artifacts/blobs").rglob("*.blob"))) == 1
    with pytest.raises(DomainError, match="ARTIFACT_NOT_FOUND"):
        await artifacts.read("bob", first["id"])
    await artifacts.delete("alice", first["id"])
    await artifacts.delete("alice", first["id"])
    with pytest.raises(DomainError, match="ARTIFACT_NOT_FOUND"):
        await artifacts.get("alice", first["id"])
    new = await artifacts.put("alice", b"evidence", mime_type="text/plain", name="report.txt")
    assert new["id"] != first["id"]
    assert (await artifacts.read("bob", other["id"]))[1] == b"evidence"
    assert [item["id"] for item in await artifacts.list("alice")] == [new["id"]]
    assert "path" not in first and "owner_id" not in first


async def test_artifact_scope_cannot_attach_another_owners_task_or_an_unrelated_message(
    artifacts, store
):
    conversations = Conversations(store)
    alice = await conversations.create("alice")
    unrelated = await conversations.create("alice")
    bob = await conversations.create("bob")
    tasks = Tasks(store, conversations)
    first = await tasks.create("alice", alice["id"], "Work", key="alice", record_intent=True)
    other = await tasks.create("bob", bob["id"], "Other", key="bob", record_intent=True)
    message = await conversations.accept("alice", unrelated["id"], "unrelated", "Unrelated input")
    with pytest.raises(DomainError, match="ARTIFACT_SCOPE_NOT_FOUND"):
        await artifacts.put("alice", b"data", mime_type="text/plain", task_id=other["id"])
    with pytest.raises(DomainError, match="ARTIFACT_SCOPE_CONFLICT"):
        await artifacts.put(
            "alice",
            b"data",
            mime_type="text/plain",
            task_id=first["id"],
            message_id=message["messageId"],
        )
    assert not (store.data_root / "agent-artifacts").exists()
    worker = await store.call(
        lambda db: row(
            db,
            "SELECT m.id FROM messages m JOIN task_attempts a ON a.native_branch_id=m.branch_id WHERE a.task_id=?",
            (first["id"],),
        )
    )
    result = await artifacts.put(
        "alice", b"data", mime_type="text/plain", task_id=first["id"], message_id=worker["id"]
    )
    assert result["taskId"] == first["id"]


async def test_integrity_failure_does_not_silently_overwrite_existing_content(artifacts):
    result = await artifacts.put("alice", b"evidence", mime_type="text/plain")
    _, path = await artifacts.verified_path("alice", result["id"])
    path.chmod(0o600)
    path.write_bytes(b"tampered")
    with pytest.raises(DomainError, match="ARTIFACT_INTEGRITY_FAILED"):
        await artifacts.read("alice", result["id"])
    with pytest.raises(DomainError, match="ARTIFACT_INTEGRITY_FAILED"):
        await artifacts.put("alice", b"evidence", mime_type="text/plain")
    assert path.read_bytes() == b"tampered"


async def test_symlinked_store_and_forged_index_paths_cannot_escape_the_artifact_root(
    artifacts, store, tmp_path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.data_root / "agent-artifacts").symlink_to(outside, target_is_directory=True)
    with pytest.raises(DomainError, match="ARTIFACT_PATH_INVALID"):
        await artifacts.put("alice", b"data", mime_type="text/plain")
    assert list(outside.iterdir()) == []
    (store.data_root / "agent-artifacts").unlink()
    result = await artifacts.put("alice", b"data", mime_type="text/plain")
    await store.call(
        lambda db: db.execute(
            "UPDATE artifacts SET path='../../outside' WHERE id=?", (result["id"],)
        ),
        write=True,
    )
    with pytest.raises(DomainError, match="ARTIFACT_PATH_INVALID"):
        await artifacts.verified_path("alice", result["id"])


async def test_download_checks_owner_integrity_and_uses_attachment_headers(store):
    runtime = Runtime(store, Model())
    app = create_app(runtime, manage_lifecycle=False)
    result = await runtime.artifacts.put(
        "alice", b"download evidence", mime_type="text/plain", name="evidence.txt"
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Roami-Owner": "alice"},
        ) as client:
            path = "/v1/artifacts/" + result["id"]
            response = await client.get(path + "/content")
            assert response.status_code == 200 and response.content == b"download evidence"
            assert response.headers["content-disposition"].startswith("attachment")
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["cache-control"] == "no-store"
            assert (
                await client.get(path + "/content", headers={"X-Roami-Owner": "bob"})
            ).status_code == 404
            assert (await client.delete(path)).status_code == 200
            assert (await client.get(path + "/content")).status_code == 404
    finally:
        await runtime.close()


async def test_cancelled_file_write_finishes_before_shutdown_releases_maintenance_lock(
    store, monkeypatch
):
    runtime = Runtime(store, Model())
    started, release, completed = threading.Event(), threading.Event(), threading.Event()
    write = runtime.artifacts._write

    def gated(body):
        started.set()
        release.wait(5)
        result = write(body)
        completed.set()
        return result

    monkeypatch.setattr(runtime.artifacts, "_write", gated)
    pending = asyncio.create_task(
        runtime.artifacts.put("alice", b"evidence", mime_type="text/plain")
    )
    await asyncio.to_thread(started.wait, 2)
    assert started.is_set()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    async def shutdown():
        await runtime.close()
        await store.close()

    closing = asyncio.create_task(shutdown())
    descriptor = os.open(store.data_root / "locks/storage.lock", os.O_RDWR)
    try:
        await asyncio.sleep(0)
        assert not closing.done()
        with pytest.raises(BlockingIOError):
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        release.set()
        await closing
        assert completed.is_set()
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        release.set()
        await asyncio.gather(closing, return_exceptions=True)
        os.close(descriptor)


async def test_schema_v1_upgrades_without_losing_existing_artifacts_and_future_schema_is_rejected(
    tmp_path,
):
    path = tmp_path / "database/agents/runtime.db"
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    connection.executescript(migrations.initial_schema())
    connection.execute(
        "INSERT INTO artifacts(id,owner_id,path,mime_type,sha256,size_bytes,created_ms) VALUES('legacy','alice','legacy-path','text/plain','legacy-hash',5,1)"
    )
    connection.commit()
    connection.close()
    database = Database(path, tmp_path, managed=False)
    await database.open()
    try:
        existing = await database.call(
            lambda db: row(db, "SELECT * FROM artifacts WHERE id='legacy'")
        )
        assert existing["path"] == "legacy-path" and existing["size_bytes"] == 5
        assert existing["name"] == "artifact" and existing["metadata_json"] == "{}"
        assert (
            await database.call(
                lambda db: db.execute("SELECT MAX(version) FROM schema_meta").fetchone()[0]
            )
            == migrations.SCHEMA_VERSION
        )
        await database.call(
            lambda db: db.execute("INSERT INTO schema_meta(version,applied_ms) VALUES(999,1)"),
            write=True,
        )
    finally:
        await database.close()
    future = Database(path, tmp_path, managed=False)
    with pytest.raises(DomainError, match="AGENT_SCHEMA_UNSUPPORTED"):
        await future.open()
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT MAX(version) FROM schema_meta").fetchone()[0] == 999
    connection.close()


async def test_failed_migration_rolls_back_ddl_and_version_before_retry(tmp_path, monkeypatch):
    path = tmp_path / "database/agents/runtime.db"
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    connection.executescript(migrations.initial_schema())
    connection.close()
    original = migrations.schema_file
    monkeypatch.setattr(
        migrations,
        "schema_file",
        lambda name: (
            "ALTER TABLE artifacts ADD COLUMN partial TEXT; SELECT missing;"
            if name.startswith("0002")
            else original(name)
        ),
    )
    broken = Database(path, tmp_path, managed=False)
    with pytest.raises(sqlite3.OperationalError):
        await broken.open()
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT MAX(version) FROM schema_meta").fetchone()[0] == 1
    assert "partial" not in [
        value[1] for value in connection.execute("PRAGMA table_info(artifacts)")
    ]
    connection.close()
    monkeypatch.setattr(migrations, "schema_file", original)
    recovered = Database(path, tmp_path, managed=False)
    await recovered.open()
    await recovered.close()
