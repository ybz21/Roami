import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from series_facts import analyze

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "cases/case-99-mech-mp01/input/calendar-series.csv"
)


@pytest.fixture
def options():
    return SimpleNamespace(
        date="When",
        price="Value",
        volume="Activity",
        matrix=[],
        price_unit="points",
        volume_unit="contracts",
        short=2,
        long=3,
        sessions=252,
        calendar_timezone="UTC",
    )


def test_arithmetic_uses_sorted_observations_and_calendar_cohorts(options):
    facts, _ = analyze(FIXTURE.read_bytes(), options)
    assert (facts["from"], facts["to"], facts["rows"]) == (
        "2020-12-30",
        "2021-01-02",
        4,
    )
    assert facts["price"]["factor"] == 0.75
    assert facts["price"]["change"] == -0.25
    assert facts["drawdown"]["minimum"] == -0.5
    assert facts["drawdown"]["date"] == "2020-12-31"
    assert facts["volume"]["median"] == 6
    assert [c["value"] for c in facts["volume"]["calendarCohorts"]] == [5, 51.5]
    assert [c["rows"] for c in facts["volume"]["calendarCohorts"]] == [2, 2]
    assert facts["returns"]["std"] == 0.5
    assert facts["movingAverages"]["shortLast"] == 75
    assert facts["movingAverages"]["longLast"] == pytest.approx(200 / 3)
    assert facts["movingAverages"]["priceVsLong"] == pytest.approx(0.125)
    assert facts["movingAverages"]["crossings"] == [
        {"date": "2021-01-02", "direction": "up"}
    ]
    assert facts["correlation"]["pairCounts"][0][-1] == 3
    json.dumps(facts, allow_nan=False)


def test_source_row_order_does_not_change_chronological_analysis(options):
    header, *rows = FIXTURE.read_text().splitlines()
    baseline, _ = analyze(FIXTURE.read_bytes(), options)
    reversed_facts, _ = analyze(
        ("\n".join([header, *reversed(rows)]) + "\n").encode(), options
    )
    assert baseline == reversed_facts


def test_crossing_dates_follow_observations_and_skip_equal_windows(options):
    body = (FIXTURE.parent / "crossing-series.csv").read_bytes()
    facts, _ = analyze(body, options)
    assert facts["movingAverages"]["crossings"] == [
        {"date": "2021-01-03", "direction": "down"},
        {"date": "2021-01-04", "direction": "up"},
    ]


def test_constant_series_reports_undefined_correlations_without_nan(options):
    body = b"When,Value,Activity\n2020-12-30,50,0\n2020-12-31,50,0\n2021-01-01,50,0\n2021-01-02,50,0\n2021-01-03,50,0\n"
    facts, _ = analyze(body, options)
    assert facts["returns"]["std"] == 0
    assert facts["returns"]["excessKurtosis"] is None
    assert facts["returns"]["absoluteLag1Correlation"] is None
    assert facts["movingAverages"]["crossings"] == []
    assert all(v is None for row in facts["correlation"]["values"] for v in row)
    json.dumps(facts, allow_nan=False)


def test_calendar_timezone_changes_aware_cohorts_but_preserves_naive_dates(options):
    aware = (
        b"When,Value,Activity\n2023-12-31T23:30:00Z,10,1\n2024-01-01T23:30:00Z,11,9\n"
    )
    utc, _ = analyze(aware, options)
    assert len(utc["volume"]["calendarCohorts"]) == 2
    options.calendar_timezone = "Asia/Shanghai"
    local, _ = analyze(aware, options)
    assert local["from"] == "2024-01-01"
    assert len(local["volume"]["calendarCohorts"]) == 1
    naive = b"When,Value,Activity\n2023-12-31,10,1\n2024-01-01,11,9\n"
    facts, _ = analyze(naive, options)
    assert facts["from"] == "2023-12-31"
    assert len(facts["volume"]["calendarCohorts"]) == 2


@pytest.mark.parametrize(
    "body",
    [
        b"When,Value,Activity\nFakeDate,10,1\n2024-01-02,11,9\n",
        b"When,Value,Activity\n2024-01-01,10,1\n2024-01-01,11,9\n",
        b"When,Value,Activity\n2024-01-01,10,nan\n2024-01-02,11,9\n",
        b"When,Value,Activity\n2024-01-01,-1,1\n2024-01-02,11,9\n",
        b"When,Value,Activity\n2024-01-01,1,-1\n2024-01-02,11,9\n",
        b"When,Value,Value\n2024-01-01,1,1\n2024-01-02,11,9\n",
        b"When,Value,Activity\n2024-01-01,1,1,extra\n2024-01-02,11,9\n",
        b"When,Value,Activity\n2024-01-01,1,1\n",
    ],
)
def test_invalid_sources_require_explicit_cleaning(body, options):
    with pytest.raises(ValueError):
        analyze(body, options)


def test_derived_return_does_not_overwrite_a_source_column(options):
    options.matrix = ["Return from Value"]
    body = b"When,Value,Activity,Return from Value\n2024-01-01,10,1,700\n2024-01-02,20,9,800\n"
    facts, _ = analyze(body, options)
    assert facts["correlation"]["labels"] == [
        "Value",
        "Activity",
        "Return from Value",
        "Return from Value (derived)",
    ]
