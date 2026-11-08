"""Run the copied source-store CLI against isolated project files."""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ASSETS = Path(__file__).resolve().parents[2] / "skills/okr-development/assets"
RELATIVE = ".roami/okr/skills/dashboard-storage/scripts/sqlite_store.py"


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(ASSETS, root)
    (root / "raw.json").write_text('{"view":0}')
    return root


def invoke(project, *args, project_id="fixture-project", success=True):
    result = subprocess.run(
        [
            sys.executable,
            str(project / RELATIVE),
            "--project-root",
            str(project),
            "--project-id",
            project_id,
            *args,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if success:
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    assert result.returncode != 0
    return result.stderr


def definition():
    return {
        "table": "src_objects",
        "label": "Objects",
        "key": ["object_id"],
        "columns": [
            {"id": "object_id", "label": "Object", "type": "string", "nullable": False, "unit": ""},
            {"id": "views", "label": "Views", "type": "integer", "nullable": True, "unit": "views"},
        ],
    }


def write_file(project, name, value):
    path = project / name
    path.write_text(json.dumps(value))
    return str(path)


def setup(project):
    invoke(project, "init")
    result = invoke(
        project, "schema-apply", "--file", write_file(project, "schema.json", definition())
    )
    return result["schemaDigest"]


def row(project, value=0, **changes):
    return {
        "values": {"object_id": "fixture-object", "views": value},
        "sourceIdentity": "fixture-source",
        "accountId": "fixture-account",
        "asOf": "2026-11-09",
        "capturedAt": "2026-11-09T03:00:00+08:00",
        "expectedVersion": 0,
        "evidence": {
            "path": "raw.json",
            "sha256": hashlib.sha256((project / "raw.json").read_bytes()).hexdigest(),
        },
        **changes,
    }


def ingest(project, schema_sha, rows, key="fixture-ingest", success=True):
    request = {"ingestKey": key, "schemaDigest": schema_sha, "rows": rows}
    return invoke(
        project,
        "write",
        "--table",
        "src_objects",
        "--file",
        write_file(project, "write.json", request),
        success=success,
    )


def query(project, *extra, account="fixture-account", operation="read"):
    return invoke(
        project,
        operation,
        "--table",
        "src_objects",
        "--source-identity",
        "fixture-source",
        "--account-id",
        account,
        "--as-of",
        "2026-11-09",
        *extra,
    )


def test_complete_copied_template_initializes_empty_and_keeps_project_boundary(project):
    setup(project)
    assert query(project)["rows"] == []
    invoke(project, "init")
    assert "Another project" in invoke(project, "init", project_id="other-project", success=False)
    assert query(project)["rows"] == []


def test_project_git_ignores_generated_source_database_and_sidecars(project, tmp_path, monkeypatch):
    setup(project)
    foreign = tmp_path / "foreign.git"
    monkeypatch.setenv("GIT_DIR", str(foreign))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "foreign-index"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "foreign-worktree"))
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    subprocess.run(
        ["git", "init", "--quiet"], cwd=project, env=environment, check=True, capture_output=True
    )
    for suffix in ("", "-journal", "-wal", "-shm"):
        subprocess.run(
            ["git", "check-ignore", "--quiet", ".roami/okr/data/source.sqlite3" + suffix],
            cwd=project,
            env=environment,
            check=True,
            capture_output=True,
        )
    assert not foreign.exists()
    assert not (tmp_path / "foreign-index").exists()
    assert not (tmp_path / "foreign-worktree").exists()


def test_idempotency_versions_zero_unknown_and_account_scope(project):
    schema_sha = setup(project)
    first = ingest(project, schema_sha, [row(project)])
    assert ingest(project, schema_sha, [row(project)]) == first
    assert "different content" in ingest(project, schema_sha, [row(project, 3)], success=False)
    assert "reread" in ingest(project, schema_sha, [row(project, 3)], key="stale", success=False)
    ingest(project, schema_sha, [row(project, None, expectedVersion=1)], key="second")
    ingest(project, schema_sha, [row(project, 99, accountId="other-account")], key="other")
    versions = query(project, "--history")["rows"]
    assert [r["rowVersion"] for r in versions] == [1, 2]
    assert [r["row"]["values"]["views"] for r in versions] == [0, None]
    assert query(project)["rows"] == [versions[-1]]
    assert query(project, account="other-account")["rows"][0]["row"]["values"]["views"] == 99
    assert query(project, operation="export") == query(project)


def test_failed_second_row_rolls_back_first_and_dedup_receipt(project):
    schema_sha = setup(project)
    error = ingest(project, schema_sha, [row(project), row(project, True)], success=False)
    assert "Field type" in error
    assert query(project)["rows"] == []
    assert ingest(project, schema_sha, [row(project)])["rows"][0]["rowVersion"] == 1


def test_two_writers_cannot_both_claim_the_same_row_version(project):
    schema_sha = setup(project)
    commands = []
    for number in range(2):
        request = {
            "ingestKey": f"parallel-{number}",
            "schemaDigest": schema_sha,
            "rows": [row(project, number)],
        }
        commands.append(
            [
                sys.executable,
                str(project / RELATIVE),
                "--project-root",
                str(project),
                "--project-id",
                "fixture-project",
                "write",
                "--table",
                "src_objects",
                "--file",
                write_file(project, f"parallel-{number}.json", request),
            ]
        )

    def run(command):
        return subprocess.run(command, check=False, capture_output=True, text=True, timeout=10)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, commands))
    assert sorted(r.returncode for r in results) == [0, 1]
    assert "reread" in next(r.stderr for r in results if r.returncode)
    assert len(query(project, "--history")["rows"]) == 1


def test_source_queries_do_not_write_the_database(project):
    schema_sha = setup(project)
    ingest(project, schema_sha, [row(project)])
    path = project / ".roami/okr/data/source.sqlite3"
    before = path.read_bytes()
    query(project)
    query(project, operation="export")
    assert path.read_bytes() == before


def test_schema_extension_keeps_frozen_old_rows_and_refuses_reinterpretation(project):
    old_sha = setup(project)
    original = ingest(project, old_sha, [row(project)])
    extended = definition()
    extended["columns"].append(
        {"id": "note", "label": "Note", "type": "string", "nullable": True, "unit": ""}
    )
    new = invoke(project, "schema-apply", "--file", write_file(project, "schema.json", extended))
    assert new["schemaDigest"] != old_sha
    assert ingest(project, old_sha, [row(project)]) == original
    assert query(project)["rows"][0]["schemaDigest"] == old_sha
    assert "schema digest" in ingest(
        project, old_sha, [row(project)], key="stale-schema", success=False
    )
    extended["columns"][1]["unit"] = "clicks"
    assert "migration" in invoke(
        project,
        "schema-apply",
        "--file",
        write_file(project, "schema.json", extended),
        success=False,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"capturedAt": "2026-11-09T03:00:00"},
        {"asOf": "20261109"},
        {"evidence": {"path": "../outside.json", "sha256": "0" * 64}},
        {"evidence": {"path": "raw.json", "sha256": "0" * 64}},
        {"accountId": 2072236826807705600},
    ],
)
def test_invalid_source_rows_do_not_publish_or_leave_partial_writes(project, changes):
    schema_sha = setup(project)
    ingest(project, schema_sha, [row(project, **changes)], success=False)
    assert query(project)["rows"] == []


def test_consistent_backup_preserves_old_versions_and_refuses_overwrite(project):
    schema_sha = setup(project)
    ingest(project, schema_sha, [row(project)])
    invoke(project, "backup", "--output", "backups/source.sqlite3")
    with sqlite3.connect(project / "backups/source.sqlite3") as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM src_objects").fetchone()[0] == 1
    assert "exists" in invoke(
        project, "backup", "--output", "backups/source.sqlite3", success=False
    )
    ingest(project, schema_sha, [row(project, 5, expectedVersion=1)], key="later")
    with sqlite3.connect(project / "backups/source.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM src_objects").fetchone()[0] == 1


def test_template_database_cannot_escape_through_symlink(project, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    directory = project / ".roami/okr/data"
    shutil.rmtree(directory)
    directory.symlink_to(outside, target_is_directory=True)
    assert "inside this project" in invoke(project, "init", success=False)
    assert list(outside.iterdir()) == []
