"""Recovered errors remain visible and cannot pass as a process improvement."""

import copy
import json

from test_improvement import trial

from roami_agent.improvement.domain.comparison import compare
from roami_agent.improvement.integrations.tool_process import (
    logged_tool_process,
    tool_process_metrics,
)


def receipt(state="succeeded", *, turn="main", **result):
    return {
        "state": state,
        "turn_id": turn,
        "result_json": json.dumps({"text": json.dumps(result)}),
    }


def test_recovered_argument_rejection_and_shell_failure_still_count():
    metrics = tool_process_metrics(
        [
            receipt("failed", error="INVALID_TOOL_ARGUMENTS", executionStarted=False),
            receipt(exitCode=0),
            receipt(exitCode=2),
            receipt(turn="worker", exitCode=0),
        ]
    )
    assert metrics["tool_calls"] == 4
    assert metrics["tool_failures"] == metrics["tool_errors"] == 2
    assert metrics["tool_argument_failures"] == metrics["tool_admission_failures"] == 1
    assert metrics["tool_error_rate"] == 0.5
    assert metrics["tool_process_score"] == 50
    assert metrics["tool_first_attempt_success_rate"] == 0.5
    assert metrics["tool_failure_codes"] == {"INVALID_TOOL_ARGUMENTS": 1, "COMMAND_NONZERO_EXIT": 1}


def test_unknown_or_missing_tool_evidence_is_not_zero_error_rate():
    unknown = tool_process_metrics(
        [receipt("unknown", error="TOOL_OUTCOME_UNKNOWN"), receipt()], complete=False
    )
    assert unknown["tool_unknowns"] == 1
    assert unknown["tool_errors"] == 1
    assert unknown["tool_process_coverage"] == "partial"
    assert unknown["tool_error_rate"] is None
    assert tool_process_metrics([])["tool_first_attempt_success_rate"] is None


def test_final_success_and_faster_delivery_cannot_hide_process_regression():
    baseline = trial(
        "process", metrics={"tokens": 100, "elapsed_ms": 100, **tool_process_metrics([receipt()])}
    )
    candidate = copy.deepcopy(baseline)
    candidate["metrics"] = {
        "tokens": 50,
        "elapsed_ms": 50,
        **tool_process_metrics(
            [
                receipt("failed", error="TOOL_DISABLED", executionStarted=False),
                receipt(),
            ]
        ),
    }
    result = compare([baseline], [candidate])
    assert result["baseline_pass_regressions"] == []
    assert result["tool_process_regressions"] == ["process"]
    assert "tool_process_regression" in result["reasons"]
    assert not result["eligible_for_promotion"]


def test_missing_baseline_process_measurement_requires_rerun():
    baseline = trial("missing")
    candidate = copy.deepcopy(baseline)
    candidate["metrics"].update(tool_process_metrics([receipt()]))
    assert compare([baseline], [candidate])["tool_process_unmeasured_cases"] == ["missing"]


def test_invalid_interruption_log_does_not_fall_back_to_old_complete_log(tmp_path):
    (tmp_path / "execution-log.json").write_text(json.dumps({"tool_calls": [receipt()]}))
    assert logged_tool_process(tmp_path)["tool_error_rate"] == 0
    (tmp_path / "interrupted-execution-log.json").write_text("incomplete JSON")
    assert logged_tool_process(tmp_path) == {"tool_process_coverage": "missing"}
