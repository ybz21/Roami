import asyncio
import base64
import io
import json
import tarfile
import time

import pytest

from roami_agent.improvement import containers
from roami_agent.improvement.project_runtime import ProjectRuntime
from roami_agent.improvement.project_snapshot import copy_project_snapshot, unpack_project
from roami_agent.improvement.protocol_suite import protocol_suite
from roami_agent.improvement.swe_tasks import (
    canonical_archive,
    parse_test_statuses,
    patch_paths,
    prepare_project,
)
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings


def archive(files):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return output.getvalue()


def test_snapshot_is_deterministic_and_never_follows_project_links(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "code.py").write_text("print(1)")
    (project / ".git").mkdir()
    (project / ".git/HEAD").write_text("not part of execution source")
    first = copy_project_snapshot(project, tmp_path / "first")
    second = copy_project_snapshot(project, tmp_path / "second")
    assert first == second and not (tmp_path / "first/.git").exists()
    secret = tmp_path / "outside"
    secret.write_text("do not copy")
    (project / "escape.py").symlink_to(secret)
    with pytest.raises(DomainError, match="SPECIAL_FILE"):
        copy_project_snapshot(project, tmp_path / "rejected")
    assert not (tmp_path / "rejected/escape.py").exists()
    (tmp_path / "root-link").symlink_to(project)
    with pytest.raises(OSError):
        copy_project_snapshot(tmp_path / "root-link", tmp_path / "bad-root")


@pytest.mark.parametrize("name", ["/outside", "../outside", "a/../../outside"])
def test_archive_paths_cannot_escape_owned_directory(tmp_path, name):
    with pytest.raises(DomainError, match="ARCHIVE_PATH"):
        unpack_project(archive({name: b"bad"}), tmp_path / "project")
    assert not (tmp_path / "outside").exists()


def test_archive_rejects_links_and_duplicate_files(tmp_path):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as tar:
        info = tarfile.TarInfo("alias")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    with pytest.raises(DomainError, match="SPECIAL_FILE"):
        unpack_project(output.getvalue(), tmp_path / "link")
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as tar:
        for _ in range(2):
            info = tarfile.TarInfo("code.py")
            info.size = 1
            tar.addfile(info, io.BytesIO(b"1"))
    with pytest.raises(DomainError, match="DUPLICATE"):
        unpack_project(output.getvalue(), tmp_path / "duplicate")


def test_canonical_source_and_new_git_baseline_do_not_include_future_history(tmp_path):
    raw = archive({"./source.py": b"print(1)\n", "./README": b"description"})
    frozen = canonical_archive(raw)
    assert frozen == canonical_archive(raw)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    chunk = base64.b64encode(frozen).decode()
    (workspace / "source.tgz").write_bytes(frozen)
    import hashlib

    case = {
        "judge": {
            "archive_parts": ["source.tgz"],
            "archive_sha256": hashlib.sha256(frozen).hexdigest(),
        },
        "asset_files": {"source.tgz": chunk},
    }
    prepare_project(case, workspace)
    assert (workspace / "project/.git/HEAD").is_file()
    assert not (workspace / "source.tgz").exists()
    assert (workspace / "project/source.py").read_text() == "print(1)\n"
    with pytest.raises(DomainError, match="SPECIAL_FILE"):
        canonical_archive(archive({".git/secret": b"no"}))


def test_patch_must_only_modify_production_python_and_statuses_are_explicit():
    patch = "diff --git a/pylint/lint/run.py b/pylint/lint/run.py\n--- a/pylint/lint/run.py\n+++ b/pylint/lint/run.py\n@@ -1 +1 @@\n-old\n+new\n"
    assert patch_paths(patch, "pylint/") == ["pylint/lint/run.py"]
    for target in [
        "tests/check.py",
        "pylint/../escape.py",
        "pylint/tests/check.py",
        "pylint/conftest.py",
        "pylint/settings.ini",
    ]:
        with pytest.raises(DomainError):
            patch_paths(patch.replace("pylint/lint/run.py", target), "pylint/")
    statuses = parse_test_statuses(
        "PASSED tests/test_one.py::test_one\nSKIPPED tests/test_one.py::test_two\nXFAIL tests/test_one.py::test_three\nFAILED tests/test_one.py::test_one\n"
    )
    assert statuses["tests/test_one.py::test_one"] != {"PASSED"}
    assert statuses["tests/test_one.py::test_two"] != {"PASSED"}
    assert statuses.get("missing") != {"PASSED"}


async def test_native_bridge_has_no_network_or_writable_agent_snapshot(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "code.py").write_text("print(1)")
    calls = []

    async def docker(*args, **kwargs):
        calls.append(args)
        if args[0] == "start":
            return b"3.9\nRSI_PROJECT_EXIT:0\n"
        if args[0] == "inspect":
            return json.dumps([{"Config": {"Labels": {"roami.rsi": args[1]}}}]).encode()
        return b""

    monkeypatch.setattr(containers, "docker_command", docker)
    bridge = ProjectRuntime(
        tmp_path / "native.sock", "frozen-image", project, time.monotonic() + 10
    )
    result = await bridge.execute(["--version"])
    assert result["exit_code"] == 0 and bridge.records[0]["source_snapshot"]["files"] == 1
    create = next(c for c in calls if c[0] == "create")
    assert create[create.index("--network") + 1] == "none" and "--read-only" in create
    mount = create[create.index("--mount") + 1]
    assert "dst=/testbed,readonly" in mount and str(project) + "," not in mount
    bridge.deadline = time.monotonic() - 1
    with pytest.raises(DomainError, match="TIME_BUDGET"):
        await bridge.execute(["--version"])
    assert len([c for c in calls if c[0] == "create"]) == 1


async def test_preparation_deadline_prevents_provider_creation(tmp_path, monkeypatch):
    case = protocol_suite()["cases"][0]
    case["limits"]["seconds"] = 0.001
    original = containers.materialize

    def slow(case, workspace):
        original(case, workspace)
        time.sleep(0.005)

    def forbidden(*args):
        raise AssertionError("No paid provider may start after setup exhausted the deadline")

    monkeypatch.setattr(containers, "materialize", slow)
    executor = containers.ContainerExecutor(Settings(), provider_factory=forbidden)
    executor.image_id = "fixture"
    with pytest.raises(DomainError, match="TIME_BUDGET"):
        await executor.run(case, {}, tmp_path)


async def test_gateway_closes_its_client_connections_and_rejects_invalid_args(tmp_path):
    bridge = ProjectRuntime(tmp_path / "native.sock", "unused", tmp_path, time.monotonic() + 5)
    async with bridge:
        reader, writer = await asyncio.open_unix_connection(str(bridge.socket))
        writer.write(b'{"argv":"not-an-array"}\n')
        await writer.drain()
        response = json.loads(await reader.read())
        assert response["error"] == "RSI_PROJECT_ARGUMENTS"
        writer.close()
        await writer.wait_closed()
    assert not bridge.clients
