import subprocess
import sys

import pytest
from test_okr_collection_store import SCRIPT, STORE, publication


def rows(*values):
    return [{"publication": value, "sha256": STORE.digest(value)} for value in values]


def test_platform_time_is_converted_to_project_day_not_material_or_sample_day():
    records = rows(
        publication(objectId="old", publishedAt="2026-11-06T12:08:48+08:00"),
        publication(objectId="utc-prior-day", publishedAt="2026-11-08T16:30:00Z"),
        publication(objectId="local-end", publishedAt="2026-11-09T23:59:59+08:00"),
        publication(objectId="next-day", publishedAt="2026-11-09T16:00:00Z"),
    )
    result = STORE.publications_on(records, "2026-11-09", "Asia/Shanghai")
    assert result["registeredCount"] == 4 and result["publishedCount"] == 2
    assert [item["publication"]["objectId"] for item in result["publications"]] == [
        "utc-prior-day",
        "local-end",
    ]
    assert result["coverageSha256"] == STORE.digest(result["publications"])
    assert result["candidateOnly"] is True


def test_repeated_observation_does_not_count_a_second_publication():
    result = STORE.publications_on(rows(publication(), publication()), "2026-11-08", "UTC")
    assert result["registeredCount"] == 2 and result["publishedCount"] == 1


def test_conflicting_platform_times_are_not_hidden_by_day_filter():
    records = rows(publication(), publication(publishedAt="2026-11-06T12:00:00Z"))
    with pytest.raises(ValueError, match="Conflicting"):
        STORE.publications_on(records, "2026-11-08", "UTC")


@pytest.mark.parametrize("timestamp", ["unknown", "2026-11-09T12:00:00", ""])
def test_unknown_or_naive_timestamp_cannot_be_reported_as_zero(timestamp):
    with pytest.raises(ValueError):
        STORE.publications_on(
            rows(publication(publishedAt=timestamp)), "2026-11-09", "Asia/Shanghai"
        )


@pytest.mark.parametrize(
    "day,zone",
    [("20261109", "UTC"), ("2026-11-31", "UTC"), ("2026-11-09", "missing/zone"), ("", "")],
)
def test_invalid_project_day_or_timezone_fails(day, zone):
    with pytest.raises(ValueError):
        STORE.publications_on([], day, zone)


def test_daylight_saving_transition_uses_natural_project_day():
    result = STORE.publications_on(
        rows(
            publication(objectId="first", publishedAt="2026-11-01T05:30:00Z"),
            publication(objectId="second", publishedAt="2026-11-01T06:30:00Z"),
        ),
        "2026-11-01",
        "America/New_York",
    )
    assert result["publishedCount"] == 2


@pytest.mark.parametrize(
    "options", [["--published-on", "2026-11-09"], ["--timezone", "Asia/Shanghai"]]
)
def test_cli_requires_date_and_timezone_together_before_creating_database(tmp_path, options):
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--project",
            str(tmp_path),
            "--project-id",
            "fixture-project",
            "list-publications",
            "--platform",
            "bilibili",
            "--account-id",
            "fixture-account",
            *options,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0 and "supplied together" in result.stderr
    assert not (tmp_path / ".roami").exists()


def test_changed_source_digest_does_not_become_a_valid_statistic():
    records = rows(publication())
    records[0]["publication"]["publishedAt"] = "2026-11-09T12:00:00Z"
    with pytest.raises(ValueError, match="digest"):
        STORE.publications_on(records, "2026-11-09", "UTC")


def test_empty_registry_cannot_claim_the_account_published_nothing():
    result = STORE.publications_on([], "2026-11-09", "Asia/Shanghai")
    assert result["publishedCount"] == 0
    assert result["scope"] == "registered-project-publications"
    assert result["accountDailyCountKnown"] is False


def test_cli_filters_real_registration_timestamps_without_changing_records(tmp_path):
    import hashlib
    import json
    import sqlite3

    target = STORE.database_path(tmp_path)
    with sqlite3.connect(target) as connection:
        STORE.initialize(connection, "fixture-project")
        STORE.register(connection, publication(businessKey="older", objectId="older"))
        STORE.register(
            connection,
            publication(businessKey="today", objectId="today", publishedAt="2026-11-08T16:01:00Z"),
        )
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--project",
            str(tmp_path),
            "--project-id",
            "fixture-project",
            "list-publications",
            "--platform",
            "bilibili",
            "--account-id",
            "fixture-account",
            "--published-on",
            "2026-11-09",
            "--timezone",
            "Asia/Shanghai",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["registeredCount"] == 2 and payload["publishedCount"] == 1
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before
