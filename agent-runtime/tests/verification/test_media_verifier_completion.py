"""Scores are observed only after successful completion, even if a receipt was written."""

import base64
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_improvement_media import wav
from test_improvement_media_receipts import payload

from roami_agent.improvement.domain.contracts import digest
from roami_agent.improvement.evaluation.benchmarks.media_tasks import PROGRAM, grade_media
from roami_agent.improvement.evaluation.native_judgment import native_judgment
from roami_agent.improvement.integrations.artifact_files import materialize


@pytest.mark.parametrize("score", [0, 0.8, 1])
@pytest.mark.parametrize("termination", [1, 77, "SIGTERM"])
def test_written_receipt_from_failed_verifier_is_not_an_observed_score(score, termination):
    spec = payload(
        json.dumps({"reward": score}), status=termination if type(termination) is int else 0
    )
    if termination == "SIGTERM":
        spec["upstream_verifier"] = spec["upstream_verifier"].replace(
            "raise SystemExit(0)", "import os,signal; os.kill(os.getpid(),signal.SIGTERM)"
        )
    process = subprocess.run(
        [sys.executable, "-c", PROGRAM],
        input=json.dumps(spec).encode(),
        capture_output=True,
        check=True,
        timeout=10,
    )
    result = json.loads(process.stdout)
    assert result["checks"]["verifier_exited"] is False
    assert (
        result["native_result_sha256"]
        == hashlib.sha256(json.dumps({"reward": score}).encode()).hexdigest()
    )
    assert result["reward"] is None
    assert result["checks"]["verifier_result_valid"] is False


@pytest.mark.parametrize("score", [0, 0.8, 1])
def test_timeout_after_receipt_write_keeps_hash_without_a_score(monkeypatch, capsys, score):
    def timed_out(*args, **kwargs):
        argv = args[0]
        Path(argv[argv.index("--reward-json") + 1]).write_text(json.dumps({"reward": score}))
        raise subprocess.TimeoutExpired("native-verifier", 300)

    monkeypatch.setattr(subprocess, "run", timed_out)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload(None))))
    exec(compile(PROGRAM, "trusted_media_program.py", "exec"), {})  # noqa: S102 - trusted evaluator constant
    result = json.loads(capsys.readouterr().out)
    assert result["checks"]["verifier_exited"] is False
    assert result["native_result_sha256"] is not None
    assert result["reward"] is None
    assert result["checks"]["verifier_result_valid"] is False


@pytest.mark.parametrize("score", [0, 0.8, 1])
@pytest.mark.parametrize("exited", [False, None, 1, "true"])
async def test_host_rejects_score_without_positive_process_completion(tmp_path, score, exited):
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
                    "reward": score,
                    "checks": {"verifier_exited": exited, "verifier_result_valid": True},
                }
            ).encode()

    grade = await grade_media(case, workspace, Executor())
    assert grade["passed"] is False
    assert "native_metric" not in grade
    assert grade["checks"]["verifier_result_valid"] is False
    assert grade["checks"]["native_metric_threshold"] is False
    assert native_judgment(grade)["native_verifier_ran"] is False
