"""Reference comparisons must distinguish a real mismatch from no valid result."""

import hashlib
import json
import subprocess
import sys

import pytest
from test_improvement_slide_tasks import package

from roami_agent.improvement.domain.contracts import digest
from roami_agent.improvement.evaluation.benchmarks.slide_tasks import (
    PROGRAM,
    grade_slides,
    reference_delta,
)
from roami_agent.improvement.evaluation.native_judgment import native_judgment, report_judgments
from roami_agent.improvement.evaluation.trial_evidence import trial_summary
from roami_agent.protocol.errors import DomainError


def fixture(tmp_path):
    parts = {"ppt/presentation.xml": b"original"}
    source = package(parts)
    (tmp_path / "input.pptx").write_bytes(source)
    (tmp_path / "updated.pptx").write_bytes(source)
    return {
        "id": "slide-receipt",
        "judge": {
            "verifier": "fixture",
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "references": [reference_delta(parts, parts)] * 2,
            "options": [{}, {}],
        },
        "origin": {"verifier_sha256": digest("fixture")},
    }


@pytest.mark.parametrize("expression", ["None", "True", "'1'", "float('nan')", "2", "-1"])
def test_program_rejects_non_numeric_or_out_of_range_comparison(tmp_path, expression):
    case = fixture(tmp_path)
    case["judge"]["verifier"] = "def compare_pptx_files(*args,**kwargs):return " + expression
    program = PROGRAM.replace("/workspace", str(tmp_path))
    result = subprocess.run(
        [sys.executable, "-c", program],
        input=json.dumps(case["judge"]).encode(),
        capture_output=True,
        timeout=10,
        check=True,
    )
    receipt = json.loads(result.stdout)
    assert receipt["results"] == [None, None]
    assert receipt["errors"]


def test_program_keeps_exception_unscored_and_an_actual_zero_separate(tmp_path):
    case = fixture(tmp_path)
    case["judge"]["verifier"] = """import pathlib
def compare_pptx_files(actual,expected,**kwargs):
 if pathlib.Path(expected).stem=='0':raise ValueError('PRIVATE_REFERENCE_MUST_NOT_APPEAR')
 return 0
"""
    result = subprocess.run(
        [sys.executable, "-c", PROGRAM.replace("/workspace", str(tmp_path))],
        input=json.dumps(case["judge"]).encode(),
        capture_output=True,
        timeout=10,
        check=True,
    )
    receipt = json.loads(result.stdout)
    assert receipt["results"] == [None, 0]
    assert receipt["errors"] == ["ValueError"]
    assert b"PRIVATE_REFERENCE" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "receipt",
    [
        b"not json",
        b"null",
        b"[]",
        b"{}",
        b'{"results":[1],"errors":[]}',
        b'{"results":[true,0],"errors":[]}',
        b'{"results":["1",0],"errors":[]}',
        b'{"results":[1,0],"errors":[],"padding":"' + b"z" * 200_001 + b'"}',
    ],
)
async def test_invalid_outer_receipt_never_passes_or_becomes_a_native_zero(tmp_path, receipt):
    case = fixture(tmp_path)

    class Executor:
        async def sandbox(self, *args, **kwargs):
            return receipt

    grade = await grade_slides(case, tmp_path, Executor())
    assert not grade["passed"]
    assert "native_metric" not in grade
    assert grade["reason"] == "native_verifier_failed"
    judgment = native_judgment(grade)
    assert "native_metric" not in judgment


async def test_sandbox_timeout_is_incomplete_not_a_missing_task_grade(tmp_path):
    case = fixture(tmp_path)

    class Executor:
        async def sandbox(self, *args, **kwargs):
            raise TimeoutError("PRIVATE_REFERENCE_MUST_NOT_APPEAR")

    grade = await grade_slides(case, tmp_path, Executor())
    assert grade["reason"] == "native_verifier_failed" and not grade["passed"]
    assert "native_metric" not in grade
    assert grade["native_verifier_ran"] is False
    assert "PRIVATE_REFERENCE" not in json.dumps(grade)


async def test_missing_artifact_has_no_metric_or_reference_scores(tmp_path):
    case = fixture(tmp_path)
    (tmp_path / "updated.pptx").unlink()

    class Executor:
        async def sandbox(self, *args, **kwargs):
            pytest.fail("No artifact: do not call comparator")

    grade = await grade_slides(case, tmp_path, Executor())
    judgment = native_judgment(grade)
    assert "native_metric" not in grade and "native_reference_results" not in grade
    assert judgment["native_verifier_ran"] is False
    assert "native_metric" not in judgment


@pytest.mark.parametrize(
    "results,passed,metric", [([None, 0], False, None), ([None, 1], True, 1), ([0, 0], False, 0)]
)
async def test_partial_reference_results_reach_case_and_report_without_changing_or_acceptance(
    tmp_path, results, passed, metric
):
    case = fixture(tmp_path)

    class Executor:
        async def sandbox(self, *args, **kwargs):
            return json.dumps(
                {"results": results, "errors": ["ValueError"] if None in results else []}
            ).encode()

    grade = await grade_slides(case, tmp_path, Executor())
    summary = trial_summary(case, {"grade": grade})
    judgment = summary["native_judgment"]
    assert grade["passed"] is passed
    assert grade.get("native_metric") == metric
    assert ("native_metric" in judgment) is (metric is not None)
    assert judgment["native_reference_results"] == results
    report = report_judgments([summary])[0]
    assert report["native_reference_results"] == results
    assert ("native_metric" in report) is (metric is not None)


def test_legacy_unrun_or_exception_zero_is_not_observed():
    for checks, errors in [({}, []), ({"native_reference_match": False}, ["ValueError"])]:
        judgment = native_judgment(
            {
                "native_metric": 0,
                "native_reference_results": [0, 0],
                "native_errors": errors,
                "checks": checks,
                "grade_scope": "original_pptx_state_comparison_not_gui_or_visual_quality",
            }
        )
        assert "native_metric" not in judgment and "native_reference_results" not in judgment
        assert judgment["native_verifier_ran"] is False


async def test_partial_comparison_round_trips_owner_details_and_free_summary(tmp_path):
    from test_improvement_pipeline import setup_run

    from roami_agent.improvement.presentation.run_results import results_view
    from roami_agent.improvement.workflows.pipeline_reports import store_evaluation_summary

    case = fixture(tmp_path)

    class Executor:
        async def sandbox(self, *args, **kwargs):
            return b'{"results":[null,0],"errors":["ValueError"]}'

    grade = await grade_slides(case, tmp_path, Executor())
    service, run_id = setup_run(tmp_path / "records")
    service.runs.case("local", run_id, trial_summary({"id": "a"}, {"grade": grade}))
    service.runs.set_state("local", run_id, "failed", {"cases": 1, "passed": 0})
    saved = results_view(service.runs, "local", run_id)["runs"][0]["caseEvidence"]["a"]
    assert saved["native_judgment"]["native_reference_results"] == [None, 0]
    assert "native_metric" not in saved["native_judgment"]
    with pytest.raises(DomainError, match="RUN_NOT_FOUND"):
        results_view(service.runs, "another-owner", run_id)
    before = service.runs.get("local", run_id)
    store_evaluation_summary(service.runs, "local", run_id)
    after = service.runs.get("local", run_id)
    artifact = next(a for a in after["artifacts"] if a["name"] == "evaluation-summary.md")
    text = service.runs.read_artifact("local", run_id, artifact["id"])["text"]
    assert '"native_reference_results":' in text and "null" in text
    assert '"native_metric":' not in text
    assert before["cases"] == after["cases"] and before["summary"] == after["summary"]
