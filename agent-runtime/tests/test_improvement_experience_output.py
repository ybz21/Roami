"""Experience transfer records must preserve the executed entry's real output."""

import asyncio
import json
import sys

import pytest

from roami_agent.improvement.authored_grading import grade_authored
from roami_agent.improvement.corpus import authored_suite
from roami_agent.improvement.executors import materialize


@pytest.mark.parametrize(
    "mode", ["output", "stdout", "both", "conflict", "wrong", "missing", "type"]
)
async def test_experience_accepts_unambiguous_stdout_field(tmp_path, mode):
    case = next(c for c in authored_suite("entry-output")["cases"] if c["id"] == "LAB-05")
    workspace = tmp_path / "work"
    materialize(case, workspace)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "verify_current.py",
        cwd=workspace / "project",
        stdout=asyncio.subprocess.PIPE,
    )
    stdout, _ = await process.communicate()
    assert process.returncode == 0
    output = stdout.decode()
    for name in ["result.json", "experience.json"]:
        (workspace / name).write_text(json.dumps(case["judge"]["expected"]))
    log = {}
    if mode in {"output", "both", "conflict", "wrong", "type"}:
        log["output"] = output
    if mode in {"stdout", "both", "conflict"}:
        log["stdout"] = output
    if mode == "conflict":
        log["stdout"] = "different"
    elif mode == "wrong":
        log["output"] = "VERIFIED:unrelated"
    elif mode == "type":
        log["output"] = True
    (workspace / "transfer-log.json").write_text(json.dumps(log))
    grade = await grade_authored(case, workspace, None)
    assert grade["checks"]["actual_entry_output"] is (mode in {"output", "stdout", "both"})
    assert grade["passed"] is (mode in {"output", "stdout", "both"})
