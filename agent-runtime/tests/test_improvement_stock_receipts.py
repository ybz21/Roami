"""A broken CSV or native checkpoint must not erase independent delivery checks."""

import base64
import hashlib
import json
import os

import pytest
from test_improvement_stock_presentation import deck

from roami_agent.improvement.evaluation.benchmarks.stock_tasks import grade_stock
from roami_agent.improvement.evaluation.execution.containers import ContainerExecutor
from roami_agent.improvement.evaluation.execution.stock_environment import OUTPUTS
from roami_agent.server.configuration import Settings


@pytest.mark.parametrize("fault", ["empty", "malformed", "unicode", "checkpoint"])
async def test_native_csv_failure_preserves_other_checks_and_unscored_status(tmp_path, fault):
    image = os.environ.get("ROAMI_RSI_TEST_IMAGE")
    if not image:
        pytest.skip("Set ROAMI_RSI_TEST_IMAGE for the real verifier sandbox")
    remote = tmp_path / "stock-remote"
    remote.mkdir()
    expected = b"Date,Close\n2026-01-01,10\n2026-01-02,11\n"
    data = {
        "empty": b"",
        "malformed": b'Date,Close\n"unterminated,10\n',
        "unicode": b"\xff\xfe\x00",
        "checkpoint": expected,
    }[fault]
    (remote / "stock_cleaned.csv").write_bytes(data)
    deck(remote / "stock_analysis.pptx", "chart")
    (remote / "stock_analysis_script.md").write_text(
        "Presenter script for the requested plots. " * 5
    )
    outputs = {
        name: {"sha256": hashlib.sha256((remote / name).read_bytes()).hexdigest()}
        for name in OUTPUTS
    }
    state = {
        "initial": {"source_sha256": "source", "outputs": {}},
        "final": {"source_sha256": "source", "outputs": outputs},
    }
    (tmp_path / "stock-snapshot.json").write_text(json.dumps(state))
    before = {name: hashlib.sha256((remote / name).read_bytes()).hexdigest() for name in OUTPUTS}
    checkpoint = "def grade_checkpoint1():\n return pd.read_csv(BytesIO(get_binary_file_content_owncloud('stock_cleaned.csv','unused'))).equals(pd.read_csv('/utils/stock_data.csv'))"
    if fault == "checkpoint":
        checkpoint = (
            "def grade_checkpoint1():\n raise RuntimeError('PRIVATE_REFERENCE_SHOULD_NOT_LEAK')"
        )
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
    assert grade["checks"]["source_unchanged"] is True
    assert grade["checks"]["fresh_remote_outputs"] is True
    assert grade["checks"]["five_plot_slides"] is True
    assert grade["checks"]["nonempty_utf8_script"] is True
    assert grade["checks"]["native_checkpoint_completed"] is False
    assert grade["native_partial"] == {
        "scored_points": None,
        "total_points": 8,
        "unscored_points": 8,
    }
    assert grade["passed"] is False and grade["hard_passed"] is False
    assert "PRIVATE_REFERENCE" not in json.dumps(grade)
    assert before == {
        name: hashlib.sha256((remote / name).read_bytes()).hexdigest() for name in OUTPUTS
    }
