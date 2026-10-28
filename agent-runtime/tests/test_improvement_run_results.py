"""Run result views retain historical evidence without borrowing future outcomes."""

import pytest

from roami_agent.improvement.evaluation.trial_evidence import trial_summary
from roami_agent.improvement.presentation.run_results import results_view
from roami_agent.improvement.service import ImprovementStatus
from roami_agent.protocol.errors import DomainError


def run(records, key, timestamp, *, name="任务名称", case_state=None):
    ident = records.create(
        "local",
        key,
        "diagnostic",
        {
            "case_ids": ["a"],
            "case_definitions": {
                "a": {"name": name, "description": "任务描述", "layer": "public_component"}
            },
        },
    )
    with records.ledger.connection() as db:
        db.execute("UPDATE rsi_pipeline_runs SET created_ms=? WHERE id=?", (timestamp, ident))
    if case_state:
        value = trial_summary({"id": "a"}, {"grade": {"passed": False}, "metrics": {"tokens": 10}})
        value["state"] = case_state
        records.case("local", ident, value)
    return ident


def test_view_uses_frozen_names_real_nodes_and_owner_checked_artifacts(tmp_path):
    records = ImprovementStatus(tmp_path).runs
    first = run(records, "first", 100, name="最初的名称", case_state="failed")
    records.node("local", first, "evaluate", "failed", "FIXTURE_FAILED")
    records.artifact("local", first, "evaluate", "report.md", "original evidence")
    second = run(records, "second", 200, name="后来的名称", case_state="passed")
    value = results_view(records, "local", second)
    assert value["runs"][0]["caseDefinitions"][0]["name"] == "最初的名称"
    assert value["runs"][1]["caseDefinitions"][0]["description"] == "任务描述"
    assert value["runs"][0]["workflow"]["evaluate"]["state"] == "failed"
    assert value["runs"][0]["workflow"]["evaluate"]["artifacts"][0]["name"] == "report.md"
    assert value["runs"][0]["caseDefinitions"][0]["group"] == "public"
    assert value["runs"][0]["caseEvidence"] == {}
    assert value["runs"][1]["caseEvidence"]["a"]["state"] == "passed"
    with pytest.raises(DomainError, match="RUN_NOT_FOUND"):
        results_view(records, "other", second)
    earlier = results_view(records, "local", first)
    assert len(earlier["runs"]) == 1 and earlier["runs"][0]["id"] == first


def test_recomputing_history_does_not_borrow_future_contract_or_future_issue(tmp_path):
    records = ImprovementStatus(tmp_path).runs
    first = run(records, "first", 100)
    first_case = trial_summary(
        {"id": "a", "version": 1}, {"grade": {"reason": "FIRST_FAILURE"}, "metrics": {"tokens": 10}}
    )
    records.case("local", first, first_case)
    records.observations("local", first)
    second = run(records, "second", 200)
    second_case = trial_summary(
        {"id": "a", "version": 2}, {"grade": {"reason": "LATER_FAILURE"}, "metrics": {"tokens": 10}}
    )
    records.case("local", second, second_case)
    records.observations("local", second)
    records.observations("local", first)
    observations = records.get("local", first)["issues"]
    assert len(observations) == 1 and observations[0]["code"] == "FIRST_FAILURE"
    assert observations[0]["status"] == "present"
    value = results_view(records, "local", first)
    assert len(value["issues"]) == 1
    assert value["issues"][0]["name"] == "FIRST_FAILURE"


@pytest.mark.parametrize("state", ["blocked", "unknown", "cancelled"])
def test_incomplete_outcomes_keep_their_state_and_do_not_become_scored_passes(tmp_path, state):
    records = ImprovementStatus(tmp_path).runs
    ident = run(records, state, 100, case_state=state)
    records.set_state("local", ident, "failed")
    records.node("local", ident, "verify", "succeeded")
    value = results_view(records, "local", ident)["runs"][0]
    assert value["results"]["a"] == state and value["state"] == "partial"
    assert value["verified"] == []
    assert value["judge"].startswith("unknown:")


def test_unaccounted_pass_is_unknown_in_result_summary(tmp_path):
    records = ImprovementStatus(tmp_path).runs
    ident = run(records, "unaccounted", 100)
    records.case(
        "local",
        ident,
        trial_summary({"id": "a"}, {"grade": {"passed": True}, "metrics": {"tokens": None}}),
    )
    records.set_state("local", ident, "succeeded")
    value = results_view(records, "local", ident)["runs"][0]
    assert value["results"]["a"] == "unknown" and value["state"] == "partial"


def test_incomplete_history_keeps_uncovered_older_issues_visible(tmp_path):
    records = ImprovementStatus(tmp_path).runs
    first = run(records, "original", 1)
    records.case(
        "local",
        first,
        trial_summary({"id": "a"}, {"grade": {"reason": "OLD_FAILURE"}, "metrics": {"tokens": 10}}),
    )
    records.observations("local", first)
    for number in range(2, 103):
        current = run(records, "history-" + str(number), number)
    records.observations("local", current)
    view = results_view(records, "local", current)
    assert not view["history_complete"] and len(view["runs"]) == 100
    assert view["runs"][0]["sequence"] == 3
    assert len(view["issues"]) == 1 and view["issues"][0]["originalRun"] == first
    assert view["issues"][0]["historyTruncated"] is True
