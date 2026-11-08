"""Exercise the copied template's project boundary and publication conflicts."""

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/okr-development/assets/.roami/okr/skills/collection-store/scripts/collection_store.py"
)
SPEC = importlib.util.spec_from_file_location("okr_collection_store", SCRIPT)
STORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STORE)


def publication(**changes):
    return {
        "businessKey": "fixture-publication-01",
        "platform": "bilibili",
        "accountId": "fixture-account",
        "objectId": "fixture-object",
        "url": "https://example.invalid/fixture-object",
        "publishedAt": "2026-11-08T12:00:00Z",
        "mainReviewReceipt": "fixture-main-review",
        "evidenceSha256": "a" * 64,
        **changes,
    }


def test_project_id_is_not_replaceable(tmp_path):
    with sqlite3.connect(STORE.database_path(tmp_path)) as connection:
        STORE.initialize(connection, "fixture-project-a")
        STORE.initialize(connection, "fixture-project-a")
        with pytest.raises(ValueError, match="another project"):
            STORE.initialize(connection, "fixture-project-b")


def test_publication_idempotency_cas_and_identity(tmp_path):
    with sqlite3.connect(STORE.database_path(tmp_path)) as connection:
        STORE.initialize(connection, "fixture-project-a")
        initial = STORE.register(connection, publication())
        assert initial["changed"] is True
        assert STORE.register(connection, publication())["changed"] is False
        updated = publication(evidenceSha256="b" * 64)
        with pytest.raises(ValueError, match="reread"):
            STORE.register(connection, updated)
        assert STORE.register(connection, updated, initial["sha256"])["changed"] is True
        with pytest.raises(ValueError, match="reread"):
            STORE.register(connection, publication(), initial["sha256"])
        with pytest.raises(ValueError, match="immutable"):
            STORE.register(connection, publication(accountId="another-account"))
        with pytest.raises(sqlite3.IntegrityError):
            STORE.register(connection, publication(businessKey="another-key"))
        row = connection.execute("SELECT content FROM publications").fetchone()
        assert json.loads(row[0]) == updated
        history = connection.execute(
            "SELECT version, content FROM publication_versions ORDER BY version"
        ).fetchall()
        assert [(row[0], json.loads(row[1])) for row in history] == [
            (1, publication()),
            (2, updated),
        ]


def test_symlink_cannot_create_outside_project(tmp_path):
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (project / ".roami").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="inside this project"):
        STORE.database_path(project)
    assert not (outside / "okr").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"accountId": True},
        {"evidenceSha256": "bad"},
        {"url": "http://example.invalid"},
        {"publishedAt": "2026-11-08T12:00:00"},
        {"publishedAt": "yesterday"},
    ],
)
def test_invalid_publication_rejected(changes):
    with pytest.raises(ValueError):
        STORE.validate_publication(publication(**changes))


def test_cli_filters_account_and_preserves_prior_versions(tmp_path):
    command = [
        sys.executable,
        str(SCRIPT),
        "--project",
        str(tmp_path),
        "--project-id",
        "fixture-project",
    ]

    def invoke(*args):
        result = subprocess.run(command + list(args), capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    invoke("init")
    for value in [
        publication(),
        publication(businessKey="fixture-other", accountId="fixture-other"),
    ]:
        request = tmp_path / "registration.json"
        request.write_text(json.dumps(value))
        invoke("register-publication", "--file", str(request))
    result = invoke(
        "list-publications", "--platform", "bilibili", "--account-id", "fixture-account"
    )
    assert [row["publication"] for row in result["publications"]] == [publication()]
    assert result["coverageSha256"] == STORE.digest(result["publications"])
    history = invoke("publication-history", "--business-key", "fixture-publication-01")
    assert history["versions"] == [
        {"version": 1, "publication": publication(), "sha256": STORE.digest(publication())}
    ]
