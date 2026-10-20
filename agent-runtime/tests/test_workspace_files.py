"""Source-checked edits are bounded, scoped, and never overwrite a changed file."""

import asyncio
import hashlib
import os
import threading

import pytest

from roami_agent.protocol.errors import DomainError, ToolCancellation
from roami_agent.server.configuration import Settings
from roami_agent.storage.workspace_files import WorkspaceFiles
from roami_agent.tools.files import register_file_tools
from roami_agent.tools.registry import Tools


@pytest.fixture
async def files():
    service = WorkspaceFiles(Settings())
    try:
        yield service
    finally:
        await service.close()


def bound(tmp_path):
    return {"taskId": "task", "workspace": {"directory": str(tmp_path)}}


async def test_write_patch_read_and_conflicts_preserve_actual_file(files, tmp_path):
    binding = bound(tmp_path)
    created = await files.write(
        {"path": "answer.txt", "expectedSha256": None, "content": "First answer\n"}, binding
    )
    path = tmp_path / "answer.txt"
    path.chmod(0o750)
    read = await files.read({"path": "answer.txt"}, binding)
    assert read["data"] == "First answer\n" and read["sha256"] == created["sha256"]
    patched = await files.patch(
        {
            "path": "answer.txt",
            "expectedSha256": read["sha256"],
            "oldText": "First",
            "newText": "Final",
        },
        binding,
    )
    assert path.read_text() == "Final answer\n" and path.stat().st_mode & 0o777 == 0o750
    assert patched["previousSha256"] == created["sha256"]
    with pytest.raises(DomainError, match="FILE_CHANGED"):
        await files.write(
            {"path": "answer.txt", "expectedSha256": created["sha256"], "content": "Lost update"},
            binding,
        )
    with pytest.raises(DomainError, match="FILE_CHANGED"):
        await files.write(
            {"path": "answer.txt", "expectedSha256": None, "content": "Lost update"}, binding
        )
    assert path.read_text() == "Final answer\n"
    assert not list(tmp_path.glob(".roami-write-*"))


async def test_ambiguous_patch_and_external_edit_do_not_change_the_file(files, tmp_path):
    binding = bound(tmp_path)
    path = tmp_path / "answer.txt"
    path.write_text("same same")
    observed = await files.read({"path": "answer.txt"}, binding)
    with pytest.raises(DomainError, match="FILE_PATCH_AMBIGUOUS"):
        await files.patch(
            {
                "path": "answer.txt",
                "expectedSha256": observed["sha256"],
                "oldText": "same",
                "newText": "changed",
            },
            binding,
        )
    path.write_text("Human edit")
    with pytest.raises(DomainError, match="FILE_CHANGED"):
        await files.patch(
            {
                "path": "answer.txt",
                "expectedSha256": observed["sha256"],
                "oldText": "same",
                "newText": "changed",
            },
            binding,
        )
    assert path.read_text() == "Human edit"


async def test_changed_source_during_temp_file_publication_is_rechecked(
    files, tmp_path, monkeypatch
):
    binding = bound(tmp_path)
    path = tmp_path / "answer.txt"
    path.write_text("original")
    digest = hashlib.sha256(b"original").hexdigest()
    fsync = os.fsync
    changed = False

    def change_before_commit(descriptor):
        nonlocal changed
        if not changed:
            changed = True
            path.write_text("Human edit")
        fsync(descriptor)

    monkeypatch.setattr(os, "fsync", change_before_commit)
    with pytest.raises(DomainError, match="FILE_CHANGED"):
        await files.write(
            {"path": "answer.txt", "expectedSha256": digest, "content": "Agent edit"}, binding
        )
    assert path.read_text() == "Human edit"
    assert not list(tmp_path.glob(".roami-write-*"))


async def test_byte_pages_have_stable_full_hash_and_binary_encoding(files, tmp_path):
    content = b"a" * 18000 + b"\xff\0"
    (tmp_path / "binary.dat").write_bytes(content)
    first = await files.read({"path": "binary.dat"}, bound(tmp_path))
    last = await files.read({"path": "binary.dat", "offset": first["nextOffset"]}, bound(tmp_path))
    assert first["readBytes"] == 16000 and first["nextOffset"] == 16000
    assert last["encoding"] == "base64" and last["nextOffset"] is None
    assert first["sha256"] == last["sha256"] == hashlib.sha256(content).hexdigest()


async def test_workspace_scope_rejects_escape_symlinks_and_special_files(files, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private").write_text("not in this task")
    (workspace / "linked").symlink_to(outside, target_is_directory=True)
    (workspace / "file-link").symlink_to(outside / "private")
    os.mkfifo(workspace / "pipe")
    for path in [
        "../outside/private",
        str(outside / "private"),
        "linked/private",
        "file-link",
        "pipe",
    ]:
        with pytest.raises(DomainError):
            await files.read({"path": path}, bound(workspace))
    with pytest.raises(DomainError, match="TASK_WORKSPACE_REQUIRED"):
        await files.read({"path": str(outside / "private")}, {"taskId": "unprepared"})
    assert (outside / "private").read_text() == "not in this task"


async def test_cancel_waits_for_actual_file_io_and_shutdown_drains_it(files, tmp_path, monkeypatch):
    started, release = threading.Event(), threading.Event()
    original = files._modify

    def blocked(*args):
        started.set()
        release.wait(5)
        return original(*args)

    monkeypatch.setattr(files, "_modify", blocked)
    task = asyncio.create_task(
        files.write({"path": "answer", "expectedSha256": None, "content": "done"}, bound(tmp_path))
    )
    await asyncio.to_thread(started.wait, 2)
    task.cancel()
    await asyncio.sleep(0.02)
    assert not task.done()
    release.set()
    with pytest.raises(ToolCancellation) as cancelled:
        await task
    assert cancelled.value.input_stopped
    await files.close()
    assert (tmp_path / "answer").read_text() == "done"


async def test_main_cannot_use_worker_file_tools(files):
    registry = Tools()
    register_file_tools(registry, files)
    assert not registry.catalog("main")
    assert {item["function"]["name"] for item in registry.catalog("worker")} == {
        "file_read",
        "file_write",
        "file_patch",
    }
    with pytest.raises(DomainError, match="TOOL_UNAVAILABLE"):
        await registry.invoke({"function": {"name": "file_write", "arguments": "{}"}}, "main", {})


async def test_unconfirmed_io_stop_is_retained_until_shutdown_can_drain(
    files, tmp_path, monkeypatch
):
    started, release = threading.Event(), threading.Event()
    original = files._modify

    def blocked(*args):
        started.set()
        release.wait(5)
        return original(*args)

    monkeypatch.setattr(files, "_modify", blocked)
    task = asyncio.create_task(
        files.write({"path": "answer", "expectedSha256": None, "content": "done"}, bound(tmp_path))
    )
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        with pytest.raises(ToolCancellation) as cancelled:
            await task
        assert not cancelled.value.input_stopped and files.pending
        closing = asyncio.create_task(files.close())
        await asyncio.sleep(0.02)
        assert not closing.done()
    finally:
        release.set()
    await closing
    assert not files.pending and (tmp_path / "answer").read_text() == "done"


async def test_publication_sync_failure_is_unknown_and_does_not_revert_or_retry(
    files, tmp_path, monkeypatch
):
    fsync = os.fsync
    calls = 0

    def fail_directory_sync(descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("directory sync failed")
        fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_directory_sync)
    with pytest.raises(DomainError, match="TOOL_OUTCOME_UNKNOWN"):
        await files.write(
            {"path": "answer", "expectedSha256": None, "content": "published"}, bound(tmp_path)
        )
    assert (tmp_path / "answer").read_text() == "published"
    assert not list(tmp_path.glob(".roami-write-*"))


async def test_large_file_pages_preserve_symlink_protection(files, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("original")
    (workspace / "link").symlink_to(outside)
    with pytest.raises(DomainError, match="FILE_ACCESS_FAILED"):
        await files.write(
            {
                "path": "link",
                "expectedSha256": hashlib.sha256(b"original").hexdigest(),
                "content": "overwrite",
            },
            bound(workspace),
        )
    assert outside.read_text() == "original" and (workspace / "link").is_symlink()
    with (workspace / "large").open("wb") as file:
        file.truncate(5 * 1024 * 1024)
    observed = await files.read(
        {"path": "large", "offset": 4 * 1024 * 1024, "limit": 1}, bound(workspace)
    )
    assert observed["data"] == "\0" and observed["sizeBytes"] == 5 * 1024 * 1024
    assert observed["readBytes"] == 1 and observed["nextOffset"] == 4 * 1024 * 1024 + 1
