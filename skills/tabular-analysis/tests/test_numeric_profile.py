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


def test_return_extremes_belong_to_current_record_with_previous_record_evidence(
    tmp_path,
):
    fixture = Path(__file__).parent / "fixtures/extrema.csv"
    source = tmp_path / "input.csv"
    source.write_bytes(fixture.read_bytes())
    before = source.read_bytes()
    result = profile(
        Workspace(tmp_path),
        "input.csv",
        ["Price"],
        "fractional_change",
        labels=["Date", "Code"],
    )
    extrema = result["columns"]["Price"]["extrema"]
    low, high = extrema["minimum"], extrema["maximum"]
    assert low["value"] == pytest.approx(-0.25)
    assert low["dataRow"] == 3 and low["labels"] == {
        "Date": "2025-01-06",
        "Code": "003",
    }
    assert low["previous"]["dataRow"] == 2
    assert low["previous"]["labels"]["Date"] == "2025-01-03"
    assert high["value"] == pytest.approx(0.5)
    assert high["labels"]["Date"] == "2025-01-07"
    assert high["previous"]["labels"]["Date"] == "2025-01-06"
    assert high["sourceValue"] == "135" and high["previous"]["sourceValue"] == "90"
    assert low["occurrences"] == high["occurrences"] == 1
    assert source.read_bytes() == before


def test_tied_extrema_count_all_occurrences_and_keep_first_input_record(tmp_path):
    csv_file(
        tmp_path, "value,label\n1,first low\n2,first high\n1,last low\n2,last high\n"
    )
    result = profile(Workspace(tmp_path), "input.csv", ["value"], labels=["label"])
    extrema = result["columns"]["value"]["extrema"]
    assert extrema["minimum"]["dataRow"] == 1
    assert extrema["minimum"]["labels"] == {"label": "first low"}
    assert extrema["maximum"]["dataRow"] == 2
    assert extrema["maximum"]["labels"] == {"label": "first high"}
    assert extrema["minimum"]["occurrences"] == extrema["maximum"]["occurrences"] == 2
    assert "previous" not in extrema["maximum"]


def test_missing_cells_break_extreme_pairing_and_unrequested_labels_are_omitted(
    tmp_path,
):
    csv_file(tmp_path, 'price,private label\n100,a\n110,b\n"",c\n200,d\n180,e\n')
    result = profile(Workspace(tmp_path), "input.csv", ["price"], "fractional_change")
    extrema = result["columns"]["price"]["extrema"]
    assert extrema["minimum"]["dataRow"] == 5
    assert extrema["minimum"]["previous"]["dataRow"] == 4
    assert extrema["maximum"]["dataRow"] == 2
    assert extrema["maximum"]["previous"]["dataRow"] == 1
    assert extrema["maximum"]["labels"] == {}
    assert "private label" not in str(extrema)


@pytest.mark.parametrize("labels", [["missing"], ["x", "x"]])
def test_invalid_label_columns_are_rejected(tmp_path, labels):
    csv_file(tmp_path, "x\n1\n")
    with pytest.raises(PublicationError, match="TABLE_FIELD_SELECTION_INVALID"):
        profile(Workspace(tmp_path), "input.csv", ["x"], labels=labels)


def test_empty_observations_have_no_extreme_record(tmp_path):
    csv_file(tmp_path, 'x\n""\n')
    result = profile(Workspace(tmp_path), "input.csv", ["x"])
    assert result["columns"]["x"]["extrema"] == {"minimum": None, "maximum": None}


def test_cli_returns_source_labels_for_current_and_previous_record(tmp_path):
    source = tmp_path / "input.csv"
    source.write_bytes((Path(__file__).parent / "fixtures/extrema.csv").read_bytes())
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "numeric_profile.py"),
            "--workspace",
            str(tmp_path),
            "--path",
            "input.csv",
            "--columns",
            "Price",
            "--transform",
            "fractional_change",
            "--labels",
            "Date",
            "Code",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    extrema = json.loads(result.stdout)["columns"]["Price"]["extrema"]
    assert extrema["maximum"]["labels"]["Date"] == "2025-01-07"
    assert extrema["minimum"]["previous"]["labels"]["Date"] == "2025-01-03"
