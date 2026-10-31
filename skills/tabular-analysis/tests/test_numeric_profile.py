"""Actual source snapshots and moment definitions, without reference task answers."""

import csv
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from distribution_moments import moments
from numeric_profile import profile
from table_publication import PublicationError, Workspace


def csv_file(tmp_path, content):
    file = tmp_path / "input.csv"
    file.write_text(content)
    return file


def test_named_moments_distinguish_normal_baselines():
    with (Path(__file__).parent / "fixtures/moments.csv").open() as source:
        values = [float(row["value"]) for row in csv.DictReader(source)]
    result = moments(values)
    assert result["kurtosisPearsonPopulation"] == 1
    assert result["kurtosisExcessPopulation"] == -2
    assert result["kurtosisExcessUnbiased"] == -6
    assert result["standardDeviationSample"] == pytest.approx(math.sqrt(4 / 3))


@pytest.mark.parametrize("values", [[], [1], [4, 4, 4, 4]])
def test_unavailable_moments_are_null_not_normal(values):
    result = moments(values)
    assert result["kurtosisPearsonPopulation"] is None
    assert result["kurtosisExcessUnbiased"] is None
    assert result["unavailable"] in {"constant_values", "no_observations"}
    json.dumps(result, allow_nan=False)


def test_sample_correction_requires_four_observations():
    result = moments([1, 2, 3])
    assert result["kurtosisPearsonPopulation"] == pytest.approx(1.5)
    assert result["kurtosisExcessUnbiased"] is None


@pytest.mark.parametrize("scale", [1e-200, 1e200])
def test_moment_ratios_survive_unit_scaling(scale):
    original = moments([-2, -1, 1, 2])
    scaled = moments([x * scale for x in [-2, -1, 1, 2]])
    for name in [
        "kurtosisPearsonPopulation",
        "kurtosisExcessPopulation",
        "kurtosisExcessUnbiased",
    ]:
        assert scaled[name] == pytest.approx(original[name])
    assert scaled["standardDeviationSample"] == pytest.approx(
        original["standardDeviationSample"] * scale
    )


def test_profile_preserves_bytes_and_reports_actual_source(tmp_path):
    file = csv_file(tmp_path, "Daily return,identifier\n-1,001\n-1,002\n1,003\n1,004\n")
    before = file.read_bytes()
    value = profile(Workspace(tmp_path), "input.csv", ["Daily return"])
    assert (
        file.read_bytes() == before
        and value["source"]["sha256"] == hashlib.sha256(before).hexdigest()
    )
    assert value["columns"]["Daily return"]["kurtosisPearsonPopulation"] == 1
    assert value["source"]["rows"] == 4 and "identifier" not in value["columns"]


def test_fractional_changes_use_adjacent_order_and_skip_no_gaps(tmp_path):
    csv_file(tmp_path, 'price\n100\n110\n""\n220\n198\n')
    value = profile(Workspace(tmp_path), "input.csv", ["price"], "fractional_change")
    stats = value["columns"]["price"]
    assert stats["observations"] == 2 and stats["sourceMissingCells"] == 1
    assert stats["mean"] == pytest.approx(0)
    assert stats["minimum"] == pytest.approx(-0.1) and stats[
        "maximum"
    ] == pytest.approx(0.1)


@pytest.mark.parametrize("cell", ["NaN", "inf", "bad", "1e400"])
def test_invalid_numeric_values_are_not_silently_omitted(tmp_path, cell):
    csv_file(tmp_path, "x\n" + cell + "\n")
    with pytest.raises(PublicationError, match="TABLE_NUMERIC_VALUE_INVALID"):
        profile(Workspace(tmp_path), "input.csv", ["x"])


def test_zero_base_requires_explicit_cleaning(tmp_path):
    csv_file(tmp_path, "x\n0\n2\n")
    with pytest.raises(PublicationError, match="TABLE_CHANGE_ZERO_BASE"):
        profile(Workspace(tmp_path), "input.csv", ["x"], "fractional_change")


@pytest.mark.parametrize("columns", [["missing"], ["x", "x"]])
def test_invalid_selection_does_not_fall_back_to_other_fields(tmp_path, columns):
    csv_file(tmp_path, "x\n1\n")
    with pytest.raises(PublicationError, match="TABLE_FIELD_SELECTION_INVALID"):
        profile(Workspace(tmp_path), "input.csv", columns)


def test_changed_source_hash_stops_before_calculation(tmp_path):
    csv_file(tmp_path, "x\n1\n")
    with pytest.raises(PublicationError, match="SOURCE_CHANGED"):
        profile(Workspace(tmp_path), "input.csv", ["x"], expected="0" * 64)


def test_cli_emits_parseable_evidence_without_creating_an_output(tmp_path):
    csv_file(tmp_path, "x\n-1\n-1\n1\n1\n")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "numeric_profile.py"),
            "--workspace",
            str(tmp_path),
            "--path",
            "input.csv",
            "--columns",
            "x",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["columns"]["x"]["kurtosisExcessUnbiased"] == -6
    assert [p.name for p in tmp_path.iterdir()] == ["input.csv"]
