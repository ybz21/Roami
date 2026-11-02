"""Keep actual native scores visible without changing task outcomes or exposing oracles."""

import json

import pytest
from test_improvement_pipeline import setup_run

from roami_agent.improvement.evaluation.native_judgment import native_judgment, report_judgments
from roami_agent.improvement.evaluation.trial_evidence import trial_summary
from roami_agent.improvement.presentation.run_results import results_view
from roami_agent.improvement.workflows.pipeline_reports import (
    PipelineReportWorker,
    public_issue_body,
    store_evaluation_summary,
)
from roami_agent.protocol.errors import DomainError


def grade(**extra):
    return {
        "passed": False,
        "hard_passed": False,
        "quality": 0,
        "checks": {"native_metric_threshold": False, "verifier_exited": True},
        "reason": "native_metric_below_threshold",
        "native_metric": 0.75,
        "native_metric_minimum": 1.0,
        "grade_scope": "original_media_verifier_plus_frozen_delivery_checks",
        "official_leaderboard_comparable": False,
        "golden": "PRIVATE_ORACLE_MUST_NOT_APPEAR",
        "diagnostic": "PRIVATE_ORACLE_MUST_NOT_APPEAR",
        **extra,
    }


def outcome(**extra):
    return trial_summary({"id": "a"}, {"grade": grade(**extra), "metrics": {"tokens": 10}})


def test_scores_reach_owner_scoped_case_details_and_free_report_without_changing_state(tmp_path):
    service, run_id = setup_run(tmp_path)
    records = service.runs
    case = outcome()
    records.case("local", run_id, case)
    records.observations("local", run_id)
    records.set_state("local", run_id, "failed", {"cases": 1, "passed": 0})
    before = records.get("local", run_id)
    details = results_view(records, "local", run_id)["runs"][0]
    saved = details["caseEvidence"]["a"]
    assert saved["state"] == "failed" and saved["quality"] == 0
    assert saved["native_judgment"]["native_metric"] == 0.75
    assert saved["native_judgment"]["native_metric_minimum"] == 1
    assert saved["native_judgment"]["official_leaderboard_comparable"] is False
    with pytest.raises(DomainError, match="RUN_NOT_FOUND"):
        results_view(records, "another-owner", run_id)
    store_evaluation_summary(records, "local", run_id)
    after = records.get("local", run_id)
    artifact = next(a for a in after["artifacts"] if a["name"] == "evaluation-summary.md")
    text = records.read_artifact("local", run_id, artifact["id"])["text"]
    assert '"native_metric": 0.75' in text and '"native_metric_minimum": 1.0' in text
    assert "PRIVATE_ORACLE" not in text and after["cases"] == before["cases"]
    assert after["summary"] == before["summary"] and after["state"] == before["state"]


async def test_codex_review_receives_native_values_instead_of_only_failed_boolean(
    tmp_path, monkeypatch
):
    service, run_id = setup_run(tmp_path)
    records = service.runs
    records.case("local", run_id, outcome())
    records.observations("local", run_id)
    records.set_state("local", run_id, "report_queued", {"cases": 1, "generation_tokens": 10})
    calls = []

    async def codex(costs, action, config, mode, prompt, **kwargs):
        calls.append(action["kind"])
        value = json.loads(prompt[0]["content"].split("\n", 1)[1])
        if action["kind"] == "review":
            assert value["cases"][0]["native_judgments"][0]["native_metric"] == 0.75
            assert value["cases"][0]["native_judgments"][0]["native_metric_minimum"] == 1
            assert "PRIVATE_ORACLE" not in json.dumps(value)
            response = {"document": "Fixture review of actual score"}
        else:
            response = {"priorities": [{"id": i["id"], "priority": "P2"} for i in value]}
        return {"text": json.dumps(response), "metrics": {"tokens": 1}}

    monkeypatch.setattr("roami_agent.improvement.workflows.pipeline_reports.codex_json", codex)
    await PipelineReportWorker(service).execute(records.claim_report())
    assert calls == ["review", "issue"]
    assert records.get("local", run_id)["state"] == "completed"


@pytest.mark.parametrize("value", [0, 1, 0.1203002])
def test_real_zero_and_fractional_native_scores_are_not_lost(value):
    summary = outcome(native_metric=value)
    assert summary["native_judgment"]["native_metric"] == value
    assert summary["state"] == "failed" and not summary["passed"]


@pytest.mark.parametrize("value", [True, None, "0.9", float("nan"), float("inf"), -1, 2])
def test_unknown_or_invalid_metric_is_not_fabricated_as_zero(value):
    assert native_judgment({"native_metric": value}) == {}


@pytest.mark.parametrize("scores", [[0, 0], [0, 1]])
def test_reference_alternatives_keep_each_score_without_changing_acceptance(scores):
    summary = outcome(
        native_reference_results=scores, checks={"native_reference_match": any(scores)}
    )
    assert summary["native_judgment"]["native_reference_results"] == scores
    assert summary["state"] == "failed"
    scores.append(1)
    assert len(summary["native_judgment"]["native_reference_results"]) == 2


@pytest.mark.parametrize("scored,unscored", [(0, 7), (1, 7), (None, 8)])
def test_partial_or_unrun_stock_checkpoint_keeps_unscored_points(scored, unscored):
    partial = {"scored_points": scored, "total_points": 8, "unscored_points": unscored}
    summary = outcome(native_partial=partial)
    assert summary["native_judgment"]["native_partial"] == partial
    assert summary["state"] == "failed" and summary["quality"] == 0


@pytest.mark.parametrize(
    "extra",
    [
        {"native_reference_results": [True]},
        {"native_reference_results": [float("nan")]},
        {"native_reference_results": [0] * 9},
        {"native_partial": {"scored_points": 2, "total_points": 1, "unscored_points": 0}},
        {"native_partial": {"scored_points": None, "total_points": 8, "unscored_points": 7}},
    ],
)
def test_invalid_extra_scores_are_omitted(extra):
    saved = outcome(**extra)["native_judgment"]
    assert not set(extra) & set(saved)


def test_reports_preserve_paired_arms_without_borrowing_selected_result():
    selected = outcome()
    selected["arm_results"] = {"baseline": outcome(native_metric=0), "candidate": outcome()}
    rows = report_judgments([selected])
    assert [(r["arm"], r["native_metric"]) for r in rows] == [("baseline", 0), ("candidate", 0.75)]


def test_legacy_summary_and_report_do_not_invent_native_scores():
    summary = trial_summary({"id": "a"}, {"grade": {"passed": False}})
    assert "native_judgment" not in summary
    run = {"id": "legacy", "mode": "diagnostic", "summary": {}, "cases": [summary], "issues": []}
    assert "native_judgments" not in public_issue_body(run, {})


@pytest.mark.parametrize("exited", [None, False])
def test_unrun_media_verifier_does_not_invent_an_observed_zero(exited):
    checks = {} if exited is None else {"verifier_exited": exited}
    summary = outcome(native_metric=0, checks=checks)
    judgment = summary["native_judgment"]
    assert "native_metric" not in judgment and judgment["native_verifier_ran"] is False
    assert judgment["native_metric_minimum"] == 1
    assert "native_metric" not in report_judgments([summary])[0]
    assert summary["state"] == "failed"


def test_unrun_slide_comparison_does_not_claim_two_reference_mismatches():
    summary = outcome(
        grade_scope="original_pptx_state_comparison_not_gui_or_visual_quality",
        checks={"artifact:updated.pptx": False},
        native_metric=0,
        native_reference_results=[0, 0],
    )
    assert "native_reference_results" not in summary["native_judgment"]
    assert summary["state"] == "failed"


def test_case_file_evidence_includes_actual_video_and_audio_outputs(tmp_path):
    workspace = tmp_path / "workspace" / "output"
    workspace.mkdir(parents=True)
    for name in ["solution.mp4", "enhanced.wav"]:
        (workspace / name).write_bytes(b"fixture artifact bytes")
    summary = trial_summary({"id": "media"}, {"grade": {}}, tmp_path)
    assert set(summary["files"]) == {"output/solution.mp4", "output/enhanced.wav"}
