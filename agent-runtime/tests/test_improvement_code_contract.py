"""Private contract outputs are compared outside the student's sandbox."""

import json

import pytest

from roami_agent.improvement.cli import execute
from roami_agent.improvement.code_contract import grade_code_contract
from roami_agent.improvement.contracts import agent_view, freeze_suite
from roami_agent.improvement.control import ImprovementControl
from roami_agent.improvement.grading import judge_case
from roami_agent.improvement.ledger import Ledger
from roami_agent.protocol.errors import DomainError


def private_case():
    return {
        "id": "private-original",
        "category": "CODE",
        "layer": "authored_real",
        "split": "holdout",
        "cluster": "original-family",
        "prompt": "Implement solution.py exporting solve(data).",
        "counts_as_delivery": True,
        "files": {"input.json": "[1,2]"},
        "limits": {"seconds": 30, "tokens": 64000, "requests": 4},
        "judge": {
            "kind": "python_contract",
            "module": "solution.py",
            "probes": [[1, 2]],
            "expected": [{"secret_answer": 73}],
        },
    }


async def test_expected_answers_never_cross_student_sandbox(tmp_path):
    case = private_case()
    (tmp_path / "solution.py").write_text("def solve(data): return data\n")

    class Capture:
        async def sandbox(self, workspace, program, **kwargs):
            payload = kwargs["input"].decode()
            assert "secret_answer" not in payload + program
            assert "expected" not in payload + program
            assert json.loads(payload) == {"module": "solution.py", "inputs": [[1, 2]]}
            return json.dumps({"results": [{"secret_answer": 73}]}).encode()

    assert "secret_answer" not in json.dumps(agent_view(case, tmp_path))
    assert judge_case(case, "", tmp_path)["pending"]
    grade = await grade_code_contract(case, tmp_path, Capture())
    assert (
        grade["passed"]
        and grade["probe_count"] == 1
        and grade["evidence"][0]["path"] == "solution.py"
    )


async def test_fabricated_student_result_is_not_accepted(tmp_path):
    case = private_case()
    (tmp_path / "solution.py").write_text("def solve(data): return None\n")

    class Wrong:
        async def sandbox(self, *args, **kwargs):
            return b'{"results":[null]}'

    assert not (await grade_code_contract(case, tmp_path, Wrong()))["passed"]
    case["judge"]["module"] = "../oracle.py"
    with pytest.raises(DomainError):
        freeze_suite("invalid", [case])


async def test_local_suite_registration_and_settings_cli(tmp_path):
    from types import SimpleNamespace

    path = tmp_path / "private.json"
    path.write_text(json.dumps(freeze_suite("private", [private_case()])))
    ledger = tmp_path / "ledger.sqlite3"
    summary = await execute(
        SimpleNamespace(command="register-suite", ledger=ledger, owner="owner", source=path)
    )
    assert summary["count"] == 1 and summary["splits"] == {"holdout": 1}
    control = ImprovementControl(Ledger(ledger))
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(control.preferences("owner")))
    result = await execute(
        SimpleNamespace(command="evaluation-config", ledger=ledger, owner="owner", config=settings)
    )
    assert not result["enabled"]
    assert control.catalog("other")["suites"] == []
