"""Transport adaptation must not add data-cleaning constraints from the grader."""

import base64
import hashlib
import json
import os

import pytest
from test_improvement_stock_presentation import deck

from roami_agent.improvement.evaluation.benchmarks.stock_tasks import grade_stock, import_stock
from roami_agent.improvement.evaluation.execution.containers import ContainerExecutor
from roami_agent.improvement.evaluation.execution.stock_environment import OUTPUTS
from roami_agent.server.configuration import Settings


@pytest.mark.parametrize(
    "instruction",
    [
        "Clean missing or inconsistent stock data and prepare a presentation.",
        "Keep the original row order. Clean missing stock values and prepare a presentation.",
    ],
)
def test_import_keeps_the_task_without_adding_grader_cleaning_instructions(tmp_path, instruction):
    task = tmp_path / "workspaces/tasks/ds-stock-analysis-slides"
    task.mkdir(parents=True)
    (task / "task.md").write_text(instruction)
    verifier = "def grade_checkpoint1():\n golden_df = None\n return False\n"
    (task / "evaluator.py").write_text(verifier)
    golden = b"Date,Close\n2026-01-01,10\n2026-01-02,11\n"
    (task / "stock_data.csv").write_bytes(golden)
    raw = tmp_path / "raw.csv"
    raw.write_bytes(b"Date,Close\n2026-01-02,11\n2026-01-01,10\n")
    suite = import_stock(
        tmp_path,
        image="ghcr.io/theagentcompany/servers-owncloud@sha256:" + "a" * 64,
        raw_source=raw,
        revision="b" * 40,
    )
    case = suite["cases"][0]
    assert case["prompt"].startswith(instruction + "\n\n")
    adaptation = case["prompt"][len(instruction) :]
    assert "preserving schema, types and row order" not in adaptation
    assert "numeric gate" not in adaptation and "rtol=" not in adaptation
    assert "stock-http.py GET|MKCOL|PUT" in adaptation
    assert "local files alone do not count as delivery" in adaptation
    assert "Do not replay writes with unknown outcomes" in adaptation
    assert case["judge"]["verifier"] == verifier
    assert base64.b64decode(case["judge"]["golden"]) == golden
    assert case["judge"]["raw_sha256"] == hashlib.sha256(raw.read_bytes()).hexdigest()
    assert "rtol=1e-12/atol=1e-10" in case["origin"]["adaptation"]


@pytest.mark.parametrize("fault", [None, "row_order", "column_type", "value"])
async def test_prompt_repair_does_not_relax_the_real_csv_grader(tmp_path, fault):
    image = os.environ.get("ROAMI_RSI_TEST_IMAGE")
    if not image:
        pytest.skip("Set ROAMI_RSI_TEST_IMAGE for the real verifier sandbox")
    expected = b"Date,Close\n2026-01-01,10\n2026-01-02,11\n"
    candidate = {
        None: expected,
        "row_order": b"Date,Close\n2026-01-02,11\n2026-01-01,10\n",
        "column_type": b"Date,Close\n2026-01-01,10.0\n2026-01-02,11.0\n",
        "value": b"Date,Close\n2026-01-01,10\n2026-01-02,99\n",
    }[fault]
    remote = tmp_path / "stock-remote"
    remote.mkdir()
    (remote / "stock_cleaned.csv").write_bytes(candidate)
    deck(remote / "stock_analysis.pptx", "chart")
    (remote / "stock_analysis_script.md").write_text("Presenter notes for the stock plots. " * 5)
    outputs = {
        name: {"sha256": hashlib.sha256((remote / name).read_bytes()).hexdigest()}
        for name in OUTPUTS
    }
    (tmp_path / "stock-snapshot.json").write_text(
        json.dumps(
            {
                "initial": {"source_sha256": "source", "outputs": {}},
                "final": {"source_sha256": "source", "outputs": outputs},
            }
        )
    )
    case = {
        "judge": {
            "raw_sha256": "source",
            "golden": base64.b64encode(expected).decode(),
            "checkpoint": "def grade_checkpoint1():\n return pd.read_csv('/workspace/stock_cleaned.csv').equals(pd.read_csv('/utils/stock_data.csv'))",
        }
    }
    executor = ContainerExecutor(Settings(), image=image)

    class Readonly:
        async def sandbox(self, workspace, program, **kwargs):
            return await executor.sandbox(workspace, program, copy_workspace=True, **kwargs)

    grade = await grade_stock(case, Readonly(), root=tmp_path)
    assert grade["checks"]["adapted_csv_values"] is (fault is None)
    assert grade["native_partial"]["scored_points"] == int(fault is None)
    assert grade["hard_passed"] is (fault is None)
    assert grade["pending"] is (fault is None)
    assert grade["passed"] is False and grade["quality"] == 0
    assert (
        hashlib.sha256((remote / "stock_cleaned.csv").read_bytes()).hexdigest()
        == outputs["stock_cleaned.csv"]["sha256"]
    )
