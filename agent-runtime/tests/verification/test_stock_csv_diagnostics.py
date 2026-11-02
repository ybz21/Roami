"""CSV failure categories survive reporting without revealing reference data."""

import base64
import hashlib
import json
import os

import pytest
from test_improvement_stock_presentation import deck

from roami_agent.improvement.evaluation.benchmarks.stock_tasks import grade_stock
from roami_agent.improvement.evaluation.execution.containers import ContainerExecutor
from roami_agent.improvement.evaluation.execution.stock_environment import OUTPUTS
from roami_agent.improvement.evaluation.native_judgment import native_judgment, report_judgments
from roami_agent.improvement.evaluation.trial_evidence import trial_summary
from roami_agent.improvement.presentation.run_results import results_view
from roami_agent.improvement.workflows.pipeline_reports import store_evaluation_summary
from roami_agent.server.configuration import Settings


@pytest.mark.parametrize(
    "fault,category,rows,columns",
    [
        ("column_count", "column_count", 2, 3),
        ("columns", "columns", 2, 2),
        ("row_count", "row_count", 1, 2),
        ("dtypes", "dtypes", 2, 2),
        ("values", "values", 2, 2),
        ("empty", "unreadable", None, None),
        ("valid", "passed", 2, 2),
        ("roundoff", "passed", 2, 2),
    ],
)
async def test_real_csv_comparison_explains_failure_without_reference_values(
    tmp_path, fault, category, rows, columns
):
    image = os.environ.get("ROAMI_RSI_TEST_IMAGE")
    if not image:
        pytest.skip("Set ROAMI_RSI_TEST_IMAGE for the real verifier sandbox")
    expected = b"Date,Close\n2026-01-01,10.25\n2026-01-02,11.25\n"
    data = {
        "column_count": b"Date,Close,Derived\n2026-01-01,10.25,1\n2026-01-02,11.25,2\n",
        "columns": b"Close,Date\n10.25,2026-01-01\n11.25,2026-01-02\n",
        "row_count": b"Date,Close\n2026-01-01,10.25\n",
        "dtypes": b"Date,Close\n2026-01-01,not_numeric\n2026-01-02,not_numeric\n",
        "values": b"Date,Close\n2026-01-01,PUBLIC_OUTPUT\n2026-01-02,PUBLIC_OUTPUT\n",
        "empty": b"",
        "valid": expected,
        "roundoff": b"Date,Close\n2026-01-01,10.25000000000001\n2026-01-02,11.25\n",
    }[fault]
    if fault == "values":
        expected = b"Date,Close\n2026-01-01,PRIVATE_REFERENCE_SENTINEL\n2026-01-02,PRIVATE_REFERENCE_SENTINEL\n"
    remote = tmp_path / "stock-remote"
    remote.mkdir()
    (remote / "stock_cleaned.csv").write_bytes(data)
    deck(remote / "stock_analysis.pptx", "chart")
    (remote / "stock_analysis_script.md").write_text("Controlled presenter fixture. " * 10)
    hashes = {name: hashlib.sha256((remote / name).read_bytes()).hexdigest() for name in OUTPUTS}
    state = {
        "initial": {"source_sha256": "source", "outputs": {}},
        "final": {
            "source_sha256": "source",
            "outputs": {name: {"sha256": sha} for name, sha in hashes.items()},
        },
    }
    (tmp_path / "stock-snapshot.json").write_text(json.dumps(state))
    checkpoint = "def grade_checkpoint1():\n return pd.read_csv(BytesIO(get_binary_file_content_owncloud('stock_cleaned.csv','unused'))).equals(pd.read_csv('/utils/stock_data.csv'))"
    case = {
        "judge": {
            "raw_sha256": "source",
            "golden": base64.b64encode(expected).decode(),
            "checkpoint": checkpoint,
        }
    }
    executor = ContainerExecutor(Settings(), image=image)

    class Readonly:
        async def sandbox(self, workspace, program, **kwargs):
            return await executor.sandbox(workspace, program, copy_workspace=True, **kwargs)

    grade = await grade_stock(case, Readonly(), root=tmp_path)
    diagnostic = grade["native_csv_diagnostic"]
    assert diagnostic == {"comparison": category, "rows": rows, "columns": columns}
    assert grade["checks"]["adapted_csv_values"] is (fault in {"valid", "roundoff"})
    assert grade["checks"]["five_plot_slides"] and grade["checks"]["nonempty_utf8_script"]
    assert grade["native_partial"]["scored_points"] == (
        None if fault == "empty" else int(fault == "valid")
    )
    assert grade["pending"] is (fault in {"valid", "roundoff"}) and not grade["passed"]
    assert "PRIVATE_REFERENCE_SENTINEL" not in json.dumps(grade)
    assert hashes == {
        name: hashlib.sha256((remote / name).read_bytes()).hexdigest() for name in OUTPUTS
    }


def grade_with_diagnostic(value):
    return {
        "passed": False,
        "hard_passed": False,
        "quality": 0,
        "grade_scope": "native_uploaded_stock_artifacts_csv_checkpoint_only_quality_pending",
        "native_partial": {"scored_points": 0, "total_points": 8, "unscored_points": 7},
        "native_csv_diagnostic": value,
    }


def test_csv_diagnostic_reaches_case_and_free_summary(tmp_path):
    from test_improvement_pipeline import setup_run

    expected = {"comparison": "column_count", "rows": 3735, "columns": 10}
    summary = trial_summary({"id": "a"}, {"grade": grade_with_diagnostic(expected)})
    assert summary["native_judgment"]["native_csv_diagnostic"] == expected
    service, run_id = setup_run(tmp_path)
    service.runs.case("local", run_id, summary)
    service.runs.set_state("local", run_id, "failed", {"cases": 1, "passed": 0})
    saved = results_view(service.runs, "local", run_id)["runs"][0]["caseEvidence"]["a"]
    assert saved["native_judgment"]["native_csv_diagnostic"] == expected
    assert saved["native_judgment"]["native_partial"]["scored_points"] == 0
    store_evaluation_summary(service.runs, "local", run_id)
    run = service.runs.get("local", run_id)
    artifact = next(a for a in run["artifacts"] if a["name"] == "evaluation-summary.md")
    text = service.runs.read_artifact("local", run_id, artifact["id"])["text"]
    assert '"native_csv_diagnostic"' in text and '"comparison": "column_count"' in text


def test_paired_arms_keep_their_own_csv_diagnostic():
    failed = {"comparison": "values", "rows": 2, "columns": 2}
    passed = {"comparison": "passed", "rows": 2, "columns": 2}
    case = {
        "case_id": "a",
        "arm_results": {
            arm: {"native_judgment": native_judgment(grade_with_diagnostic(value))}
            for arm, value in [("baseline", failed), ("candidate", passed)]
        },
    }
    records = report_judgments([case])
    assert [r["native_csv_diagnostic"] for r in records] == [failed, passed]


@pytest.mark.parametrize(
    "value",
    [
        None,
        {"comparison": "private text", "rows": 2, "columns": 2},
        {"comparison": "values", "rows": True, "columns": 2},
        {"comparison": "values", "rows": -1, "columns": 2},
        {"comparison": "values", "rows": 8_000_001, "columns": 2},
        {"comparison": "values", "rows": "2", "columns": 2},
        {"comparison": "values", "rows": None, "columns": 2},
        {"comparison": "values", "rows": 2, "columns": 2, "expected": "PRIVATE"},
    ],
)
def test_invalid_diagnostics_cannot_publish_arbitrary_or_reference_text(value):
    assert "native_csv_diagnostic" not in native_judgment(grade_with_diagnostic(value))
