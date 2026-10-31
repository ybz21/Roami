"""Type-cleaning omissions remain visible without coercing record identifiers."""

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from csv_export import export, inspect
from table_publication import Workspace

FIXTURE = Path(__file__).resolve().parent / "fixtures/numeric-representation.csv"


def snapshots(root):
    body = FIXTURE.read_bytes()
    for name in ["raw.csv", "analysis.csv"]:
        (root / name).write_bytes(body)
    return Workspace(root), body


def test_inspection_exposes_unnamed_integral_decimal_column(tmp_path):
    workspace, body = snapshots(tmp_path)
    receipt = inspect(workspace, "raw.csv")
    assert receipt["integralDecimalFields"] == [
        {
            "field": field,
            "nonemptyCount": 2,
            "numericCount": 2,
            "integralDecimalCount": 2,
            "leadingZeroCount": 0,
        }
        for field in ["", "units"]
    ]
    assert (tmp_path / "raw.csv").read_bytes() == body
    assert {p.name for p in tmp_path.iterdir()} == {"raw.csv", "analysis.csv"}


@pytest.mark.parametrize("normalize_identifier", [False, True])
def test_export_receipt_identifies_only_the_retained_omission(
    tmp_path, normalize_identifier
):
    workspace, body = snapshots(tmp_path)
    observed = {
        name: inspect(workspace, name)["sha256"] for name in ["raw.csv", "analysis.csv"]
    }
    fields = ["units", ""] if normalize_identifier else ["units"]
    receipt = export(
        workspace,
        "raw.csv",
        "analysis.csv",
        "clean.csv",
        observed["raw.csv"],
        observed["analysis.csv"],
        numeric=fields,
    )
    assert receipt["numericFields"] == (
        ["", "units"] if normalize_identifier else ["units"]
    )
    assert [v["field"] for v in receipt["retainedIntegralDecimalFields"]] == (
        [] if normalize_identifier else [""]
    )
    with (tmp_path / "clean.csv").open() as source:
        rows = list(csv.reader(source))
    assert rows[1] == [
        "1" if normalize_identifier else "1.0",
        "007",
        "2",
        "1.125",
        "first",
    ]
    assert rows[2] == [
        "2" if normalize_identifier else "2.0",
        "008",
        "3",
        "2.500",
        "second",
    ]
    assert all((tmp_path / name).read_bytes() == body for name in observed)


@pytest.mark.parametrize(
    "value", ["1e1000000000", "NaN", "Infinity", "0.0000000000001"]
)
def test_mixed_and_padded_values_are_observations_not_conversion_advice(
    tmp_path, value
):
    (tmp_path / "raw.csv").write_text(f"record,label\n007.0,one\n{value},two\n,three\n")
    receipt = inspect(Workspace(tmp_path), "raw.csv")
    profile = receipt["integralDecimalFields"][0]
    assert profile == {
        "field": "record",
        "nonemptyCount": 2,
        "numericCount": 1 if value in ["NaN", "Infinity"] else 2,
        "integralDecimalCount": 1,
        "leadingZeroCount": 1,
    }
    assert inspect(Workspace(tmp_path), "raw.csv")["sha256"] == receipt["sha256"]


def test_cli_receipt_preserves_the_exact_field_identity(tmp_path):
    snapshots(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "csv_export.py"),
            "inspect",
            "--workspace",
            str(tmp_path),
            "--path",
            "raw.csv",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    receipt = json.loads(result.stdout)
    assert receipt["ok"] and receipt["integralDecimalFields"][0]["field"] == ""


@pytest.mark.parametrize("selector", ["numeric", "keys", "columns"])
def test_json_export_can_select_an_actual_empty_header(tmp_path, selector):
    workspace, body = snapshots(tmp_path)
    spec = {
        "source": "raw.csv",
        "analysis": "analysis.csv",
        "destination": "clean.csv",
        "expectedSourceSha256": inspect(workspace, "raw.csv")["sha256"],
        "expectedAnalysisSha256": inspect(workspace, "analysis.csv")["sha256"],
        "numeric": ["units"],
    }
    if selector == "numeric":
        spec[selector].append("")
    elif selector == "columns":
        spec[selector] = ["", "record id", "units", "ratio", "label"]
    else:
        spec[selector] = [""]
    (tmp_path / "export.json").write_text(json.dumps(spec))
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
        check=True,
    )
    receipt = json.loads(result.stdout)
    with (tmp_path / "clean.csv").open() as source:
        rows = list(csv.reader(source))
    assert receipt["ok"] and rows[0][0] == ""
    assert rows[1] == [
        "1" if selector == "numeric" else "1.0",
        "007",
        "2",
        "1.125",
        "first",
    ]
    assert all(
        (tmp_path / name).read_bytes() == body for name in ["raw.csv", "analysis.csv"]
    )
