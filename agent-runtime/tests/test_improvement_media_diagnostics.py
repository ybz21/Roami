"""Media components survive records without reference data or synthetic scores."""

import base64
import json
from pathlib import Path

import pytest
from test_improvement_media import wav
from test_improvement_media_receipts import receipt

from roami_agent.improvement.domain.contracts import digest
from roami_agent.improvement.evaluation.benchmarks.media_tasks import grade_media
from roami_agent.improvement.evaluation.native_judgment import native_judgment, report_judgments
from roami_agent.improvement.evaluation.trial_evidence import trial_summary
from roami_agent.improvement.integrations.artifact_files import materialize
from roami_agent.improvement.presentation.run_results import results_view
from roami_agent.improvement.workflows.pipeline_reports import store_evaluation_summary


def sample():
    return json.loads(
        (
            Path(__file__).parents[2] / "cases/case-70-mech-md01/input/native-receipt.json"
        ).read_text()
    )


def test_actual_verifier_receipt_exports_only_public_numeric_components():
    body = sample()
    result = receipt(json.dumps(body))
    assert result["reward"] == body["reward"]
    assert result["checks"]["verifier_result_valid"] is True
    observed = result["native_audio_diagnostic"]
    assert observed["in_window_reward"] == body["in_window_reward"]
    assert observed["out_window"] == body["details"]["out_window"]
    assert observed["in_window"]["lsd_4_8kHz"] == 0.45
    assert "dnsmos_ref_ovl" not in observed["in_window"]
    assert "PRIVATE_" not in json.dumps(result)
    assert "private_start" not in json.dumps(result)


@pytest.mark.parametrize(
    "value",
    [None, True, "PRIVATE_VALUE", [], {}, float("nan"), float("inf"), -float("inf"), 10**400],
)
def test_unavailable_component_is_null_and_does_not_replace_valid_total(value):
    body = sample()
    body["details"]["in_window"]["pesq_wb"] = value
    body["out_window_reward"] = value
    result = receipt(json.dumps(body))
    assert result["reward"] == body["reward"]
    assert result["native_audio_diagnostic"]["in_window"]["pesq_wb"] is None
    assert result["native_audio_diagnostic"]["out_window_reward"] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("reward", [None, True, float("nan")])
def test_invalid_verdict_does_not_publish_components_as_a_completed_measurement(reward):
    body = sample()
    body["reward"] = reward
    result = receipt(json.dumps(body))
    assert result["reward"] is None and result["native_audio_diagnostic"] is None


def test_nonzero_verifier_exit_does_not_publish_components():
    result = receipt(json.dumps(sample()), status=1)
    assert result["reward"] is None and result["native_audio_diagnostic"] is None


async def test_components_reach_case_detail_and_report_without_changing_pass_state(tmp_path):
    source = wav(64)
    case = {
        "id": "a",
        "files": {},
        "asset_files": {"materials/noisy.wav": base64.b64encode(source).decode()},
        "judge": {
            "media_kind": "repair",
            "upstream_verifier": "fixture",
            "minimum_reward": 0.8,
            "golden": {},
        },
        "origin": {"verifier_sha256": digest("fixture")},
    }
    workspace = tmp_path / "work"
    materialize(case, workspace)
    (workspace / "output").mkdir()
    (workspace / "output/enhanced.wav").write_bytes(source)
    body = sample()
    components = {key: body[key] for key in ["in_window_reward", "out_window_reward"]}
    components.update(body["details"])
    components["in_window"]["stoi"] = float("nan")

    class Executor:
        async def sandbox(self, *args, **kwargs):
            return json.dumps(
                {
                    "reward": body["reward"],
                    "checks": {"verifier_exited": True, "verifier_result_valid": True},
                    "native_audio_diagnostic": components,
                }
            ).encode()

    grade = await grade_media(case, workspace, Executor())
    assert grade["passed"] is False and grade["native_metric"] == body["reward"]
    assert grade["reason"] == "native_metric_below_threshold"
    expected = grade["native_audio_diagnostic"]
    assert expected["in_window"]["stoi"] is None
    assert "PRIVATE_" not in json.dumps(grade)
    evidence = native_judgment(grade)
    assert evidence["native_audio_diagnostic"] == expected
    assert (
        report_judgments([{"case_id": "a", "native_judgment": evidence}])[0][
            "native_audio_diagnostic"
        ]
        == expected
    )
    from test_improvement_pipeline import setup_run

    service, run_id = setup_run(tmp_path / "records")
    service.runs.case(
        "local", run_id, trial_summary(case, {"grade": grade, "metrics": {"tokens": 0}})
    )
    service.runs.set_state("local", run_id, "failed", {"cases": 1, "passed": 0})
    saved = results_view(service.runs, "local", run_id)["runs"][0]["caseEvidence"]["a"]
    assert saved["native_judgment"]["native_audio_diagnostic"] == expected
    store_evaluation_summary(service.runs, "local", run_id)
    run = service.runs.get("local", run_id)
    artifact = next(a for a in run["artifacts"] if a["name"] == "evaluation-summary.md")
    text = service.runs.read_artifact("local", run_id, artifact["id"])["text"]
    assert '"native_audio_diagnostic":' in text and "PRIVATE_" not in text


def test_failed_measurement_removes_stale_components_and_legacy_reports_still_work():
    grade = {
        "native_metric": 0,
        "native_audio_diagnostic": {"in_window_reward": 0.55},
        "grade_scope": "original_media_verifier_plus_frozen_delivery_checks",
        "checks": {"verifier_exited": True, "verifier_result_valid": False},
    }
    observed = native_judgment(grade)
    assert "native_metric" not in observed and "native_audio_diagnostic" not in observed
    legacy = {"native_metric": 0.2, "native_metric_minimum": 0.8}
    assert native_judgment(legacy) == legacy
