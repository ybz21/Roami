"""Frozen Actor gates exclude host tools while preserving actual runtime failures."""

import json
import os
from pathlib import Path

import pytest

from roami_agent.improvement.workflows.candidate_checks import CodePairExecutor
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings


@pytest.mark.parametrize(
    "body", ["assert True", "assert False", "raise RuntimeError('runtime collection error')"]
)
async def test_frozen_gate_keeps_runtime_failures_and_excludes_host_dependencies(tmp_path, body):
    image = os.environ.get("ROAMI_RSI_TEST_IMAGE")
    if not image:
        pytest.skip("Set ROAMI_RSI_TEST_IMAGE for the real frozen regression sandbox")
    pack = tmp_path / "tests"
    pack.mkdir()
    (pack / "test_actor.py").write_text(
        f"def test_runtime():\n    {body}\n" if body.startswith("assert") else body + "\n"
    )
    (pack / "verification").mkdir()
    (pack / "test_temporary_storage.py").write_text(
        "def test_first(tmp_path):\n    (tmp_path / 'completed-fixture').write_text('data')\n"
        "def test_second(tmp_path):\n    assert not list(tmp_path.parent.rglob('completed-fixture'))\n"
    )
    for name in ["verification/test_verifier.py", "test_improvement_oracle.py"]:
        (pack / name).write_text("raise AssertionError('host-only module must not be imported')\n")
    source = Path(__file__).parents[3]
    pair = CodePairExecutor(
        Settings(),
        {
            "baseline_root": source,
            "candidate_root": source,
            "baseline_build_hash": "controlled",
            "candidate_build_hash": "controlled",
        },
    )
    executor = pair.executors["candidate"]
    executor.image, executor.regression_root = image, pack
    output = tmp_path / "receipt"
    if body == "assert True":
        result = await pair.regression(output)
        assert result["exit_code"] == 0 and "3 passed" in result["output"]
    else:
        with pytest.raises(DomainError, match="RSI_CANDIDATE_REGRESSION_FAILED"):
            await pair.regression(output)
        result = json.loads(next(output.glob("regression-*.json")).read_text())
        assert result["exit_code"] == (1 if body == "assert False" else 2)
    assert "host-only module must not be imported" not in result["output"]
