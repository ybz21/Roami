"""Terminal assertions are frozen, private to the grader and never run on the host."""

import copy
import json

import pytest

from roami_agent.improvement.contracts import agent_view
from roami_agent.improvement.grading import judge_case
from roami_agent.improvement.terminal_tasks import grade_terminal, import_terminal
from roami_agent.protocol.errors import DomainError


def terminal_case(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "instruction.md").write_text("Write /app/run.py with bounded concurrency.")
    (tmp_path / "tests/test_outputs.py").write_text(
        "def test_expected(): assert 'secret-assertion'\n"
    )
    (tmp_path / "tests/test.py").write_text("from run import run_tasks\n")
    return import_terminal(tmp_path, task_id="cancel-async-tasks", revision="a" * 40)["cases"][0]


async def test_terminal_verifier_runs_only_in_independent_sandbox(tmp_path):
    case = terminal_case(tmp_path)
    (tmp_path / "run.py").write_text("async def run_tasks(tasks,max_concurrent): pass\n")
    assert "secret-assertion" not in json.dumps(agent_view(case, tmp_path))
    assert judge_case(case, "", tmp_path)["pending"]
    calls = []

    class Sandbox:
        async def sandbox(self, workspace, program, **kwargs):
            calls.append((workspace, program, kwargs))
            return json.dumps({"exit_code": 0, "output": "1 passed"}).encode()

    grade = await grade_terminal(case, tmp_path, Sandbox())
    assert grade["passed"] and not grade["official_leaderboard_comparable"]
    assert (
        len(calls) == 1
        and json.loads(calls[0][2]["input"])["upstream_verifier"]
        == case["judge"]["upstream_verifier"]
    )


async def test_terminal_rejects_changed_verifier_before_execution(tmp_path):
    case = copy.deepcopy(terminal_case(tmp_path))
    case["judge"]["upstream_verifier"] = "def test_fake(): pass"

    class Forbidden:
        async def sandbox(self, *args, **kwargs):
            raise AssertionError("Changed verifier must not execute")

    with pytest.raises(DomainError, match="VERIFIER_CHANGED"):
        await grade_terminal(case, tmp_path, Forbidden())
