"""CSV publication uses public source schemas without dropping record identity."""

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


def fixture(root):
    (root / "raw.csv").write_text(
        "row_id,date,units,value\n007,a,2,1.25\n008,b,3,2.50\n009,c,4,3.75\n"
    )
    (root / "analysis.csv").write_text(
        "date,units,value,average\nb,3.0,2.50,2.5\na,2.0,1.25,1.875\n"
    )
    workspace = Workspace(root)
    return workspace, {
        name: inspect(workspace, name)["sha256"] for name in ["raw.csv", "analysis.csv"]
    }


def publish(workspace, hashes, **kwargs):
    return export(
        workspace,
        "raw.csv",
        "analysis.csv",
        "clean.csv",
        hashes["raw.csv"],
        hashes["analysis.csv"],
        keys=["date"],
        numeric=["units", "value"],
        **kwargs,
    )


def test_keyed_source_projection_preserves_ids_order_and_precision(tmp_path):
    workspace, hashes = fixture(tmp_path)
    receipt = publish(workspace, hashes)
    assert (
        tmp_path / "clean.csv"
    ).read_text() == "row_id,date,units,value\n008,b,3,2.50\n007,a,2,1.25\n"
    assert receipt["recoveredSourceColumns"] == ["row_id"]
    assert receipt["excludedAnalysisColumns"] == ["average"]
    assert all(
        inspect(workspace, name)["sha256"] == sha for name, sha in hashes.items()
    )


def test_explicit_feature_dataset_schema_is_supported(tmp_path):
    workspace, hashes = fixture(tmp_path)
    export(
        workspace,
        "raw.csv",
        "analysis.csv",
        "features.csv",
        hashes["raw.csv"],
        hashes["analysis.csv"],
        columns=["date", "average"],
    )
    assert (tmp_path / "features.csv").read_text() == "date,average\nb,2.5\na,1.875\n"


@pytest.mark.parametrize(
    "failure",
    [
        "source_hash",
        "analysis_hash",
        "destination",
        "ambiguous_key",
        "missing_key",
        "numeric",
        "symlink",
    ],
)
def test_invalid_or_changed_inputs_do_not_publish(tmp_path, failure):
    workspace, hashes = fixture(tmp_path)
    if failure == "source_hash":
        hashes["raw.csv"] = "0" * 64
    if failure == "analysis_hash":
        hashes["analysis.csv"] = "0" * 64
    if failure == "destination":
        (tmp_path / "clean.csv").write_text("existing")
    if failure == "ambiguous_key":
        with (tmp_path / "raw.csv").open("a") as out:
            out.write("010,a,2,1.25\n")
    if failure == "missing_key":
        (tmp_path / "analysis.csv").write_text("date,units,value\nx,3,2.5\n")
    if failure == "numeric":
        (tmp_path / "analysis.csv").write_text("date,units,value\na,NaN,2.5\n")
    if failure == "symlink":
        (tmp_path / "raw.csv").rename(tmp_path / "real.csv")
        (tmp_path / "raw.csv").symlink_to(tmp_path / "real.csv")
    if failure not in ["source_hash", "analysis_hash", "symlink"]:
        hashes = {name: inspect(workspace, name)["sha256"] for name in hashes}
    with pytest.raises((PublicationError, OSError)):
        publish(workspace, hashes)
    output = tmp_path / "clean.csv"
    assert (
        output.read_text() == "existing"
        if failure == "destination"
        else not output.exists()
    )
    assert not list(tmp_path.glob(".table-*"))


def test_cli_export_and_observed_replacement(tmp_path):
    _workspace, hashes = fixture(tmp_path)
    args = [
        sys.executable,
        str(SCRIPTS / "csv_export.py"),
        "export",
        "--workspace",
        str(tmp_path),
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
        "--keys",
        "date",
        "--numeric",
        "units",
        "value",
    ]
    first = subprocess.run(args, capture_output=True, text=True, check=False)
    assert first.returncode == 0 and json.loads(first.stdout)["ok"]
    before = (tmp_path / "clean.csv").read_bytes()
    denied = subprocess.run(args, capture_output=True, text=True, check=False)
    assert (
        denied.returncode == 1
        and json.loads(denied.stdout)["code"] == "DESTINATION_CHANGED"
    )
    replaced = subprocess.run(
        args + ["--expected-destination-sha256", hashlib.sha256(before).hexdigest()],
        capture_output=True,
        text=True,
        check=False,
    )
    assert replaced.returncode == 0 and (tmp_path / "clean.csv").read_bytes() == before


def test_both_input_snapshots_are_checked_at_publication(tmp_path, monkeypatch):
    workspace, hashes = fixture(tmp_path)
    original = workspace.read
    reads = 0

    def racing_read(path, **kwargs):
        nonlocal reads
        reads += 1
        if reads == 3:
            (tmp_path / "analysis.csv").write_text("date,units,value\na,1,2\n")
        return original(path, **kwargs)

    monkeypatch.setattr(workspace, "read", racing_read)
    with pytest.raises(PublicationError, match="SOURCE_CHANGED"):
        publish(workspace, hashes)
    assert not (tmp_path / "clean.csv").exists()


def test_analysis_cannot_be_overwritten_as_output(tmp_path):
    workspace, hashes = fixture(tmp_path)
    with pytest.raises(PublicationError, match="OUTPUT_MUST_DIFFER"):
        export(
            workspace,
            "raw.csv",
            "analysis.csv",
            "analysis.csv",
            hashes["raw.csv"],
            hashes["analysis.csv"],
            keys=["date"],
        )
    assert inspect(workspace, "analysis.csv")["sha256"] == hashes["analysis.csv"]


def test_numeric_exponents_keep_their_exact_lexical_form(tmp_path):
    workspace, hashes = fixture(tmp_path)
    (tmp_path / "analysis.csv").write_text("date,units,value\na,2.0,1e1000000000\n")
    hashes["analysis.csv"] = inspect(workspace, "analysis.csv")["sha256"]
    publish(workspace, hashes)
    assert "1e1000000000" in (tmp_path / "clean.csv").read_text()


@pytest.mark.parametrize("collision", [False, True])
def test_explicit_iso_date_keys_recover_source_identity_without_guessing(
    tmp_path, collision
):
    workspace, hashes = fixture(tmp_path)
    raw = "row_id,date,units,value\n007,2026-01-02 00:00:00+00:00,2,1.25\n008,invalid,3,2.50\n"
    if collision:
        raw += "009,2026-01-02 12:00:00+00:00,4,3.75\n"
    (tmp_path / "raw.csv").write_text(raw)
    (tmp_path / "analysis.csv").write_text("date,units,value\n2026-01-02,2.0,1.25\n")
    hashes = {name: inspect(workspace, name)["sha256"] for name in hashes}
    if collision:
        with pytest.raises(PublicationError, match="TABLE_SOURCE_KEYS_AMBIGUOUS"):
            publish(workspace, hashes, date_keys=["date"])
        assert not (tmp_path / "clean.csv").exists()
    else:
        publish(workspace, hashes, date_keys=["date"])
        assert (
            (tmp_path / "clean.csv").read_text()
            == "row_id,date,units,value\n007,2026-01-02 00:00:00+00:00,2,1.25\n"
        )


def test_selected_invalid_date_key_does_not_publish(tmp_path):
    workspace, hashes = fixture(tmp_path)
    with pytest.raises(PublicationError, match="TABLE_DATE_KEY_INVALID"):
        publish(workspace, hashes, date_keys=["date"])
    assert not (tmp_path / "clean.csv").exists()


@pytest.mark.parametrize("mode", ["source", "analysis"])
def test_source_row_filtering_is_distinct_from_edited_values(tmp_path, mode):
    workspace, hashes = fixture(tmp_path)
    (tmp_path / "analysis.csv").write_text("row_id,date,units,value\n008,b,9,99.50\n")
    hashes["analysis.csv"] = inspect(workspace, "analysis.csv")["sha256"]
    publish(workspace, hashes, value_mode=mode)
    expected = (
        "row_id,date,units,value\n008,b,3,2.50\n"
        if mode == "source"
        else "row_id,date,units,value\n008,b,9,99.50\n"
    )
    assert (tmp_path / "clean.csv").read_text() == expected


@pytest.mark.parametrize("edited_date", [False, True])
def test_complete_analysis_schema_preserves_date_identity_and_other_edits(
    tmp_path, edited_date
):
    workspace, hashes = fixture(tmp_path)
    (tmp_path / "raw.csv").write_text(
        "row_id,date,units,value\n007,2026-01-02 00:00:00+00:00,2,1.25\n"
    )
    (tmp_path / "analysis.csv").write_text(
        "row_id,date,units,value\n007,2026-01-02,9,99.50\n"
    )
    hashes = {name: inspect(workspace, name)["sha256"] for name in hashes}
    publish(workspace, hashes, date_keys=["date"], analysis_key_values=edited_date)
    date = "2026-01-02" if edited_date else "2026-01-02 00:00:00+00:00"
    assert (
        tmp_path / "clean.csv"
    ).read_text() == f"row_id,date,units,value\n007,{date},9,99.50\n"


@pytest.mark.parametrize("failure", ["AMBIGUOUS", "UNMATCHED"])
def test_complete_analysis_schema_still_validates_declared_keys(tmp_path, failure):
    workspace, hashes = fixture(tmp_path)
    (tmp_path / "analysis.csv").write_text("row_id,date,units,value\n007,a,9,99.50\n")
    if failure == "AMBIGUOUS":
        with (tmp_path / "raw.csv").open("a") as out:
            out.write("010,a,4,5\n")
    else:
        (tmp_path / "raw.csv").write_text("row_id,date,units,value\n008,b,3,2.50\n")
    hashes = {name: inspect(workspace, name)["sha256"] for name in hashes}
    with pytest.raises(PublicationError, match=f"TABLE_SOURCE_KEYS_{failure}"):
        publish(workspace, hashes)
    assert not (tmp_path / "clean.csv").exists()


def export_spec(root, hashes, **overrides):
    value = {
        "source": "raw.csv",
        "analysis": "analysis.csv",
        "destination": "clean.csv",
        "expectedSourceSha256": hashes["raw.csv"],
        "expectedAnalysisSha256": hashes["analysis.csv"],
        "keys": ["date"],
        "numeric": ["units", "value"],
        **overrides,
    }
    (root / "export.json").write_text(json.dumps(value))
    return [
        sys.executable,
        str(SCRIPTS / "csv_export.py"),
        "export",
        "--workspace",
        str(root),
        "--spec",
        "export.json",
    ]


@pytest.mark.parametrize(
    "field", ["total amount", "成交额", "value;$(touch pwned)'quote"]
)
def test_spec_preserves_field_boundaries_without_shell_interpretation(tmp_path, field):
    import csv

    workspace, hashes = fixture(tmp_path)
    for name, header, rows in [
        (
            "raw.csv",
            ["record id", "date", field],
            [["007", "a", "2.0"], ["008", "b", "3.125"]],
        ),
        ("analysis.csv", ["date", field], [["b", "3.125"], ["a", "2.0"]]),
    ]:
        with (tmp_path / name).open("w", newline="") as out:
            writer = csv.writer(out, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(rows)
    hashes = {name: inspect(workspace, name)["sha256"] for name in hashes}
    args = export_spec(tmp_path, hashes, numeric=[field])
    spec_before = (tmp_path / "export.json").read_bytes()
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["specSha256"] == hashlib.sha256(spec_before).hexdigest()
    with (tmp_path / "clean.csv").open() as source:
        assert list(csv.reader(source)) == [
            ["record id", "date", field],
            ["008", "b", "3.125"],
            ["007", "a", "2"],
        ]
    assert (tmp_path / "export.json").read_bytes() == spec_before
    assert not (tmp_path / "pwned").exists()
    assert all(
        inspect(workspace, name)["sha256"] == sha for name, sha in hashes.items()
    )


@pytest.mark.parametrize(
    "change",
    [
        {"numeric": "units value"},
        {"analysisKeyValues": "false"},
        {"expectedSourceSha256": "guessed"},
        {"numericColumns": ["units"]},
        {"keys": [123]},
        {"source": None},
    ],
)
def test_invalid_spec_does_not_publish(tmp_path, change):
    _workspace, hashes = fixture(tmp_path)
    result = subprocess.run(
        export_spec(tmp_path, hashes, **change),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    receipt = json.loads(result.stdout)
    assert receipt["code"] in ["TABLE_SPEC_VALUES_INVALID", "TABLE_SPEC_FIELDS_INVALID"]
    assert receipt["details"] and receipt["writePublished"] is False
    assert not (tmp_path / "clean.csv").exists()


@pytest.mark.parametrize(
    "body,code",
    [
        ('{"source":"a","source":"b"}', "TABLE_SPEC_DUPLICATE_FIELD"),
        ("[]", "TABLE_SPEC_OBJECT_REQUIRED"),
        ("{", "TABLE_SPEC_INVALID_JSON"),
    ],
)
def test_invalid_spec_document_is_explicit(tmp_path, body, code):
    _workspace, hashes = fixture(tmp_path)
    args = export_spec(tmp_path, hashes)
    (tmp_path / "export.json").write_text(body)
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    assert result.returncode == 1 and json.loads(result.stdout)["code"] == code
    assert not (tmp_path / "clean.csv").exists()


@pytest.mark.parametrize(
    "failure", ["changed_input", "spec_destination", "mixed_options"]
)
def test_spec_retains_snapshot_and_output_guards(tmp_path, failure):
    _workspace, hashes = fixture(tmp_path)
    args = export_spec(
        tmp_path,
        hashes,
        **({"destination": "export.json"} if failure == "spec_destination" else {}),
    )
    spec_before = (tmp_path / "export.json").read_bytes()
    if failure == "changed_input":
        (tmp_path / "raw.csv").write_text("changed")
    if failure == "mixed_options":
        args += ["--numeric", "units"]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert not (tmp_path / "clean.csv").exists()
    assert (tmp_path / "export.json").read_bytes() == spec_before
    if failure != "mixed_options":
        assert json.loads(result.stdout)["code"] == (
            "SOURCE_CHANGED" if failure == "changed_input" else "OUTPUT_MUST_DIFFER"
        )


def test_split_field_error_explains_how_to_keep_the_intended_selection(tmp_path):
    _workspace, hashes = fixture(tmp_path)
    for name in hashes:
        path = tmp_path / name
        path.write_text(path.read_text().replace("units", "total amount"))
    workspace = Workspace(tmp_path)
    hashes = {name: inspect(workspace, name)["sha256"] for name in hashes}
    args = export_spec(tmp_path, hashes, numeric=["total amount", "value"])
    direct = [
        sys.executable,
        str(SCRIPTS / "csv_export.py"),
        "export",
        "--workspace",
        str(tmp_path),
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
        "--keys",
        "date",
        "--numeric",
        "total",
        "amount",
        "value",
    ]
    failed = subprocess.run(direct, capture_output=True, text=True, check=False)
    receipt = json.loads(failed.stdout)
    assert failed.returncode == 1 and receipt["code"] == "TABLE_FIELD_SELECTION_INVALID"
    assert receipt["details"]["invalidNumericFields"] == ["amount", "total"]
    assert "total amount" in receipt["details"]["availableColumns"]
    assert "--spec" in receipt["details"]["recovery"]
    assert not (tmp_path / "clean.csv").exists()
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "008,b,3,2.50" in (tmp_path / "clean.csv").read_text()


@pytest.mark.parametrize("explicit", [False, True])
def test_spec_requires_an_explicit_numeric_selection_even_when_empty(
    tmp_path, explicit
):
    _workspace, hashes = fixture(tmp_path)
    args = export_spec(tmp_path, hashes, numeric=[], preserveNumericText=["units"])
    if not explicit:
        value = json.loads((tmp_path / "export.json").read_text())
        del value["numeric"]
        (tmp_path / "export.json").write_text(json.dumps(value))
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if explicit:
        assert result.returncode == 0
        assert "008,b,3.0,2.50" in (tmp_path / "clean.csv").read_text()
    else:
        receipt = json.loads(result.stdout)
        assert result.returncode == 1 and receipt["code"] == "TABLE_SPEC_FIELDS_INVALID"
        assert receipt["details"]["missing"] == ["numeric"]
        assert not (tmp_path / "clean.csv").exists()
