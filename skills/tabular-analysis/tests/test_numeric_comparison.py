"""Hand-computed comparisons, immutable inputs and explicit percentage definitions."""

import hashlib
import json
import os
import subprocess
import sys
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from numeric_comparison import compare
from table_publication import PublicationError, Workspace


def snapshots(tmp_path, before="x\n100\n", after="x\n30\n"):
    for name, text in [("before.csv", before), ("after.csv", after)]:
        (tmp_path / name).write_text(text)
    return Workspace(tmp_path)


def result(workspace, selected=("x",), name="median", **kwargs):
    return compare(workspace, "before.csv", "after.csv", selected, name, **kwargs)


def test_fixture_medians_report_seventy_percent_decline_without_changing_inputs(
    tmp_path,
):
    fixtures = Path(__file__).parent / "fixtures"
    for name, fixture in [
        ("before.csv", "comparison-before.csv"),
        ("after.csv", "comparison-after.csv"),
    ]:
        (tmp_path / name).write_bytes((fixtures / fixture).read_bytes())
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    receipt = result(Workspace(tmp_path), ["amount"])
    value = receipt["comparisons"]["amount"]
    assert value["baseline"]["value"] == "100" and value["current"]["value"] == "30"
    assert value["difference"] == "-70" and value["percentageDisplay"] == "-70.0%"
    assert Decimal(value["fractionalChange"]) == Decimal("-0.7")
    assert value["direction"] == "decrease" and not receipt["sourceChanged"]
    assert (
        receipt["baselineSource"]["sha256"]
        == hashlib.sha256(before["before.csv"]).hexdigest()
    )
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


@pytest.mark.parametrize(
    "name,a,b",
    [
        ("mean", 5, 7),
        ("median", 6, 8),
        ("minimum", 1, 2),
        ("maximum", 8, 11),
        ("first", 1, 2),
        ("last", 6, 8),
    ],
)
def test_explicit_statistics_use_their_own_definition(tmp_path, name, a, b):
    value = result(snapshots(tmp_path, "x\n1\n8\n6\n", "x\n2\n11\n8\n"), name=name)[
        "comparisons"
    ]["x"]
    assert Decimal(value["baseline"]["value"]) == a
    assert Decimal(value["current"]["value"]) == b
    assert Decimal(value["difference"]) == b - a
    assert value["baseline"]["observations"] == value["current"]["observations"] == 3


def test_negative_baseline_keeps_signed_formula_separate_from_numeric_direction(
    tmp_path,
):
    value = result(snapshots(tmp_path, "x\n-100\n", "x\n-50\n"))["comparisons"]["x"]
    assert value["direction"] == "increase" and value["difference"] == "50"
    assert (
        value["fractionalChange"] == "-0.5" and value["percentageDisplay"] == "-50.0%"
    )


def test_zero_baseline_does_not_invent_a_percentage(tmp_path):
    value = result(snapshots(tmp_path, "x\n0\n", "x\n5\n"))["comparisons"]["x"]
    assert value["difference"] == "5" and value["direction"] == "increase"
    assert value["fractionalChange"] is None and value["percentageDisplay"] is None
    assert value["percentageUnavailable"] == "zero_baseline"


def test_missing_cells_have_separate_explicit_counts(tmp_path):
    value = result(snapshots(tmp_path, 'x\n1\n""\n3\n', 'x\n5\n""\n'))["comparisons"][
        "x"
    ]
    assert (
        value["baseline"]["observations"] == 2 and value["current"]["observations"] == 1
    )
    assert (
        value["baseline"]["sourceMissingCells"]
        == value["current"]["sourceMissingCells"]
        == 1
    )
    assert value["difference"] == "3" and value["percentageDisplay"] == "150.0%"


def test_empty_sample_is_unavailable_instead_of_zero(tmp_path):
    with pytest.raises(PublicationError, match="TABLE_COMPARISON_EMPTY"):
        result(snapshots(tmp_path, 'x\n""\n'))


@pytest.mark.parametrize("cell", ["NaN", "Infinity", "-inf", "wrong"])
def test_invalid_numbers_are_not_silently_dropped(tmp_path, cell):
    with pytest.raises(PublicationError, match="TABLE_NUMERIC_VALUE_INVALID"):
        result(snapshots(tmp_path, "x\n" + cell + "\n"))


@pytest.mark.parametrize("selected", [[], ["unknown"], ["x", "x"]])
def test_invalid_fields_never_fall_back_to_another_column(tmp_path, selected):
    with pytest.raises(PublicationError, match="TABLE_FIELD_SELECTION_INVALID"):
        result(snapshots(tmp_path), selected)


def test_unknown_statistic_is_not_substituted(tmp_path):
    with pytest.raises(PublicationError, match="TABLE_STATISTIC_INVALID"):
        result(snapshots(tmp_path), name="mode")


@pytest.mark.parametrize("side", ["baseline", "current"])
def test_stale_source_hash_rejects_the_comparison(tmp_path, side):
    with pytest.raises(PublicationError, match="SOURCE_CHANGED"):
        result(snapshots(tmp_path), **{"expected_" + side: "0" * 64})


def test_source_mutation_during_calculation_is_not_published(tmp_path):
    snapshots(tmp_path)

    class Changing(Workspace):
        reads = 0

        def read(self, path, **kwargs):
            if path == "before.csv":
                self.reads += 1
                if self.reads == 2:
                    (self.root / path).write_text("x\n999\n")
            return super().read(path, **kwargs)

    with pytest.raises(PublicationError, match="SOURCE_CHANGED"):
        result(Changing(tmp_path))


@pytest.mark.parametrize("kind", ["outside", "symlink", "fifo", "directory"])
def test_read_scope_still_rejects_special_and_outside_files(tmp_path, kind):
    snapshots(tmp_path)
    target = tmp_path / "blocked.csv"
    if kind == "outside":
        target = tmp_path.parent / "outside.csv"
        target.write_text("x\n1\n")
    elif kind == "symlink":
        target.symlink_to(tmp_path / "before.csv")
    elif kind == "fifo":
        os.mkfifo(target)
    else:
        target.mkdir()
    with pytest.raises((PublicationError, OSError)):
        compare(Workspace(tmp_path), str(target), "after.csv", ["x"], "median")


def test_mean_retains_small_residual_after_large_cancellation(tmp_path):
    value = result(snapshots(tmp_path, "x\n1e60\n1\n-1e60\n", "x\n1\n"), name="mean")[
        "comparisons"
    ]["x"]
    assert float(value["baseline"]["value"]) == pytest.approx(1 / 3)


def test_small_relative_change_is_not_lost_before_subtraction(tmp_path):
    with localcontext() as context:
        context.prec = 100
        current = str(Decimal("1e60") + 1)
    value = result(
        snapshots(tmp_path, "x\n1e60\n", "x\n" + current + "\n"), name="first"
    )["comparisons"]["x"]
    assert value["difference"] == "1" and Decimal(value["fractionalChange"]) == Decimal(
        "1e-60"
    )
    assert value["direction"] == "increase"


def cli(tmp_path):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "numeric_comparison.py"),
            "--workspace",
            str(tmp_path),
            "--baseline",
            "before.csv",
            "--current",
            "after.csv",
            "--columns",
            "x",
            "--statistic",
            "median",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_returns_only_a_json_receipt_and_creates_no_file(tmp_path):
    snapshots(tmp_path)
    output = cli(tmp_path)
    assert output.returncode == 0
    assert (
        json.loads(output.stdout)["comparisons"]["x"]["percentageDisplay"] == "-70.0%"
    )
    assert sorted(p.name for p in tmp_path.iterdir()) == ["after.csv", "before.csv"]


def test_malformed_csv_cli_error_is_structured_and_does_not_write(tmp_path):
    snapshots(tmp_path, 'x\n"unterminated')
    output = cli(tmp_path)
    assert output.returncode == 1 and json.loads(output.stdout) == {
        "error": "TABLE_CSV_INVALID",
        "writePublished": False,
    }


def test_decimal_range_failure_is_a_json_error_instead_of_infinity(tmp_path):
    snapshots(tmp_path, "x\n1e1000000\n")
    output = cli(tmp_path)
    assert output.returncode == 1 and json.loads(output.stdout) == {
        "error": "TABLE_COMPARISON_RANGE",
        "writePublished": False,
    }
