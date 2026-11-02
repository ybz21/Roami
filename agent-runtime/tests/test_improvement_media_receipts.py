"""A completed process without a valid receipt is not an observed zero score."""

import base64
import io
import json
import subprocess
import sys

import pytest
from test_improvement_media import wav

from roami_agent.improvement.domain.contracts import digest
from roami_agent.improvement.evaluation.benchmarks.media_tasks import PROGRAM, grade_media
from roami_agent.improvement.evaluation.native_judgment import native_judgment
from roami_agent.improvement.evaluation.trial_evidence import trial_summary
from roami_agent.improvement.integrations.artifact_files import materialize
from roami_agent.improvement.presentation.run_results import results_view
from roami_agent.improvement.workflows.pipeline_reports import store_evaluation_summary


def payload(body, *, status=0):
    code = "import pathlib,sys\n"
    if body is not None:
        code += (
            "pathlib.Path(sys.argv[sys.argv.index('--reward-json')+1]).write_text("
            + repr(body)
            + ")\n"
        )
    code += "raise SystemExit(" + str(status) + ")\n"
    return {"media_kind": "repair", "upstream_verifier": code, "golden": {}}


def receipt(body, *, status=0):
    result = subprocess.run(
        [sys.executable, "-c", PROGRAM],
        input=json.dumps(payload(body, status=status)).encode(),
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr.decode()
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "body",
    [
        None,
        "{}",
        "not json",
        "[]",
        "null",
        '{"reward":true}',
        '{"reward":"0.8"}',
        '{"reward":NaN}',
        '{"reward":Infinity}',
        '{"reward":-0.1}',
        '{"reward":1.1}',
    ],
)
def test_missing_or_invalid_native_receipt_has_no_score(body):
    result = receipt(body)
    assert result["reward"] is None
    assert result["checks"]["verifier_result_valid"] is False


@pytest.mark.parametrize("score", [0, 0.8, 1])
def test_real_zero_and_valid_native_reward_are_preserved(score):
    result = receipt(json.dumps({"reward": score}))
    assert result["reward"] == score
    assert result["checks"]["verifier_exited"] is True
    assert result["checks"]["verifier_result_valid"] is True


def test_timeout_returns_a_failed_receipt_without_a_synthetic_score(monkeypatch, capsys):
    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired("native-verifier", 300)

    monkeypatch.setattr(subprocess, "run", timed_out)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload(None))))
    exec(compile(PROGRAM, "trusted_media_program.py", "exec"), {})  # noqa: S102 - trusted evaluator constant
    result = json.loads(capsys.readouterr().out)
    assert result["reward"] is None
    assert result["checks"]["verifier_exited"] is False
    assert result["checks"]["verifier_result_valid"] is False


async def test_invalid_receipt_reaches_case_evidence_without_becoming_zero(tmp_path):
    source = wav(64)
    case = {
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

    class Executor:
        async def sandbox(self, *args, **kwargs):
            return json.dumps(
                {
                    "reward": None,
                    "checks": {"verifier_exited": True, "verifier_result_valid": False},
                }
            ).encode()

    grade = await grade_media(case, workspace, Executor())
    assert grade["passed"] is False
    evidence = native_judgment(grade)
    assert "native_metric" not in evidence
    assert evidence["native_verifier_ran"] is False
    assert evidence["native_metric_minimum"] == 0.8
    from test_improvement_pipeline import setup_run

    service, run_id = setup_run(tmp_path / "records")
    service.runs.case(
        "local", run_id, trial_summary({"id": "a"}, {"grade": grade, "metrics": {"tokens": 0}})
    )
    service.runs.set_state("local", run_id, "failed", {"cases": 1, "passed": 0})
    saved = results_view(service.runs, "local", run_id)["runs"][0]["caseEvidence"]["a"]
    assert saved["native_judgment"]["native_verifier_ran"] is False
    assert "native_metric" not in saved["native_judgment"]
    store_evaluation_summary(service.runs, "local", run_id)
    run = service.runs.get("local", run_id)
    artifact = next(a for a in run["artifacts"] if a["name"] == "evaluation-summary.md")
    text = service.runs.read_artifact("local", run_id, artifact["id"])["text"]
    assert '"native_metric":' not in text
    assert '"native_metric_minimum": 0.8' in text


def test_failed_receipt_flag_prevents_legacy_zero_from_becoming_observed():
    grade = {
        "native_metric": 0,
        "native_metric_minimum": 0.8,
        "grade_scope": "original_media_verifier_plus_frozen_delivery_checks",
        "checks": {"verifier_exited": True, "verifier_result_valid": False},
    }
    evidence = native_judgment(grade)
    assert "native_metric" not in evidence and evidence["native_verifier_ran"] is False
