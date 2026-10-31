"""Unreviewed integral-decimal fields stop a write, including observed replacements."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from csv_export import export, inspect
from table_publication import PublicationError, Workspace

FIXTURE = Path(__file__).resolve().parent / "fixtures/numeric-representation.csv"


def snapshots(root):
    for name in ["raw.csv", "analysis.csv"]:
        (root / name).write_bytes(FIXTURE.read_bytes())
    workspace = Workspace(root)
    return workspace, {
        name: inspect(workspace, name)["sha256"] for name in ["raw.csv", "analysis.csv"]
    }


def specification(hashes):
    return {
        "source": "raw.csv",
        "analysis": "analysis.csv",
        "destination": "clean.csv",
        "expectedSourceSha256": hashes["raw.csv"],
        "expectedAnalysisSha256": hashes["analysis.csv"],
        "numeric": ["units"],
    }


@pytest.mark.parametrize("entry", ["api", "spec", "flags"])
def test_unselected_empty_header_stops_before_publication(tmp_path, entry):
    workspace, hashes = snapshots(tmp_path)
    if entry == "api":
        with pytest.raises(PublicationError) as raised:
            export(
                workspace,
                "raw.csv",
                "analysis.csv",
                "clean.csv",
                *hashes.values(),
                numeric=["units"],
            )
        assert str(raised.value) == "TABLE_NUMERIC_CHOICES_REQUIRED"
        assert not raised.value.published
        details = raised.value.details
    else:
        args = [
            sys.executable,
            str(SCRIPTS / "csv_export.py"),
            "export",
            "--workspace",
            str(tmp_path),
        ]
        if entry == "spec":
            (tmp_path / "export.json").write_text(json.dumps(specification(hashes)))
            args += ["--spec", "export.json"]
        else:
            args += [
                "--source",
                "raw.csv",
                "--analysis",
                "analysis.csv",
                "--destination",
                "clean.csv",
                "--expected-source-sha256",
                hashes["raw.csv"],
                "--expected-analysis-sha256",
                hashes["analysis.csv"],
                "--numeric",
                "units",
            ]
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        assert result.returncode == 1
        receipt = json.loads(result.stdout)
        assert (
            receipt["code"] == "TABLE_NUMERIC_CHOICES_REQUIRED"
            and not receipt["writePublished"]
        )
        details = receipt["details"]
    assert [x["field"] for x in details["unresolvedFields"]] == [""]
    assert details["unresolvedFields"][0]["integralDecimalCount"] == 2
    assert not (tmp_path / "clean.csv").exists()
    assert not list(tmp_path.glob(".table-*"))
    assert all(
        inspect(workspace, name)["sha256"] == sha for name, sha in hashes.items()
    )


@pytest.mark.parametrize("entry", ["spec", "flags"])
def test_explicit_preservation_is_available_through_both_cli_inputs(tmp_path, entry):
    _workspace, hashes = snapshots(tmp_path)
    args = [
        sys.executable,
        str(SCRIPTS / "csv_export.py"),
        "export",
        "--workspace",
        str(tmp_path),
    ]
    if entry == "spec":
        (tmp_path / "export.json").write_text(
            json.dumps({**specification(hashes), "preserveNumericText": [""]})
        )
        args += ["--spec", "export.json"]
    else:
        args += [
            "--source",
            "raw.csv",
            "--analysis",
            "analysis.csv",
            "--destination",
            "clean.csv",
            "--expected-source-sha256",
            hashes["raw.csv"],
            "--expected-analysis-sha256",
            hashes["analysis.csv"],
            "--numeric",
            "units",
            "--preserve-numeric-text",
            "",
        ]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    receipt = json.loads(result.stdout)
    assert receipt["preservedNumericTextFields"] == [""]
    assert receipt["numericFields"] == ["units"]
    assert [x["field"] for x in receipt["retainedIntegralDecimalFields"]] == [""]
    assert (tmp_path / "clean.csv").read_text().splitlines()[1].startswith("1.0,007,2,")


@pytest.mark.parametrize("choice", ["conflict", "missing", "invalid_type"])
def test_invalid_preservation_cannot_publish(tmp_path, choice):
    snapshots(tmp_path)
    hashes = {
        name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
        for name in ["raw.csv", "analysis.csv"]
    }
    preserve = {"conflict": ["units"], "missing": ["typo"], "invalid_type": ""}[choice]
    (tmp_path / "export.json").write_text(
        json.dumps({**specification(hashes), "preserveNumericText": preserve})
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "csv_export.py"),
            "export",
            "--workspace",
            str(tmp_path),
            "--spec",
            "export.json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    receipt = json.loads(result.stdout)
    assert result.returncode == 1 and not receipt["writePublished"]
    assert receipt["code"] == (
        "TABLE_SPEC_VALUES_INVALID"
        if choice == "invalid_type"
        else "TABLE_FIELD_SELECTION_INVALID"
    )
    if choice == "conflict":
        assert receipt["details"]["conflictingFields"] == ["units"]
    if choice == "missing":
        assert receipt["details"]["invalidPreserveFields"] == ["typo"]
    assert not (tmp_path / "clean.csv").exists()


def test_unreviewed_choice_cannot_replace_an_observed_output(tmp_path):
    workspace, hashes = snapshots(tmp_path)
    previous = b"user-owned previous output\n"
    (tmp_path / "clean.csv").write_bytes(previous)
    with pytest.raises(PublicationError, match="TABLE_NUMERIC_CHOICES_REQUIRED"):
        export(
            workspace,
            "raw.csv",
            "analysis.csv",
            "clean.csv",
            *hashes.values(),
            numeric=["units"],
            expected_destination=hashlib.sha256(previous).hexdigest(),
        )
    assert (tmp_path / "clean.csv").read_bytes() == previous
    assert not list(tmp_path.glob(".table-*"))


def test_projection_does_not_require_choices_for_excluded_fields(tmp_path):
    workspace, hashes = snapshots(tmp_path)
    receipt = export(
        workspace,
        "raw.csv",
        "analysis.csv",
        "clean.csv",
        *hashes.values(),
        columns=["units", "ratio"],
        numeric=["units"],
    )
    assert (
        receipt["columns"] == ["units", "ratio"]
        and not receipt["retainedIntegralDecimalFields"]
    )


def test_padded_and_mixed_identifier_text_is_never_automatically_converted(tmp_path):
    body = b"code,units\n007.0,2.0\nprefix-9,3.0\n"
    for name in ["raw.csv", "analysis.csv"]:
        (tmp_path / name).write_bytes(body)
    sha = hashlib.sha256(body).hexdigest()
    workspace = Workspace(tmp_path)
    with pytest.raises(PublicationError, match="TABLE_NUMERIC_CHOICES_REQUIRED"):
        export(
            workspace,
            "raw.csv",
            "analysis.csv",
            "clean.csv",
            sha,
            sha,
            numeric=["units"],
        )
    receipt = export(
        workspace,
        "raw.csv",
        "analysis.csv",
        "clean.csv",
        sha,
        sha,
        numeric=["units"],
        preserve_numeric_text=["code"],
    )
    assert receipt["preservedNumericTextFields"] == ["code"]
    assert (tmp_path / "clean.csv").read_bytes() == b"code,units\n007.0,2\nprefix-9,3\n"
