"""Executable mechanism cases need present, executed assertions to claim a pass."""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from roami_agent.improvement.evaluation import mechanisms
from roami_agent.improvement.evaluation.case_catalog import case_definitions
from roami_agent.protocol.errors import DomainError


def test_all_mechanism_selectors_resolve_and_match_case_materials():
    tests = Path(__file__).parent
    definitions = {case["id"]: case for case in case_definitions()}
    for key in mechanisms.NODES:
        ident = "MECH-" + key
        selectors = mechanisms.nodes(ident)
        for selector in selectors:
            module, function = selector.split("::")
            names = {
                n.name
                for n in ast.parse((tests / module).read_text()).body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            assert function in names, (ident, selector)
        from roami_agent.improvement.evaluation.case_catalog import case_resource

        materials = json.loads(Path(case_resource(ident, "materials.json")).read_text())
        assert definitions[ident]["kind"] == "mechanism_regression"
        assert materials["data"]["pytest_selectors"] == selectors
        assert materials["acceptance"]["pytest_selectors"] == selectors


async def test_missing_test_function_rejects_before_creating_a_container(tmp_path, monkeypatch):
    from roami_agent.improvement.evaluation.execution import containers

    selectors = mechanisms.nodes("MECH-MB02")
    for selector in selectors:
        (tmp_path / selector.split("::")[0]).write_text("def test_unrelated(): pass\n")

    async def forbidden(*args, **kwargs):
        raise AssertionError("No container may start for a missing regression")

    monkeypatch.setattr(containers, "docker_command", forbidden)
    case = {"id": "MECH-MB02", "judge": {"selectors": selectors}}
    with pytest.raises(DomainError, match="RSI_REGRESSION_NODE_REQUIRED"):
        await mechanisms.run_mechanism(
            case, {}, tmp_path, SimpleNamespace(regression_root=tmp_path)
        )


@pytest.mark.parametrize(
    ("decoration", "body", "expected"),
    [
        ("", "assert True", True),
        ("@pytest.mark.skip(reason='unavailable')", "assert False", False),
        ("@pytest.mark.xfail(reason='unresolved')", "assert False", False),
        ("@pytest.mark.xfail(reason='still unconfirmed')", "assert True", False),
        ("", "assert False", False),
    ],
)
def test_actual_pytest_receipt_requires_executed_success(tmp_path, decoration, body, expected):
    (tmp_path / "test_fixture.py").write_text(
        "import pytest\n" + decoration + "\ndef test_contract():\n " + body + "\n"
    )
    selectors = ["test_fixture.py::test_contract"]
    program = mechanisms.regression_program({}, selectors)
    program = program.replace("/testing", str(tmp_path)).replace(
        "/tmp/rsi-tests", str(tmp_path / "run")
    )
    process = subprocess.run(
        [sys.executable, "-c", program],
        cwd=tmp_path,
        env={**os.environ, "PYTEST_ADDOPTS": ""},
        text=True,
        capture_output=True,
        timeout=20,
        check=True,
    )
    receipt = json.loads(process.stdout.splitlines()[-1])
    assert receipt["collected"] == 1
    assert mechanisms.regression_passed(receipt, selectors) is expected


def test_zero_collection_and_partial_selection_cannot_claim_success():
    assert not mechanisms.regression_passed(
        {"exit_code": 0, "collected": 0, "passed": 0, "skipped": 0, "selectors": []}, ["x"]
    )
    assert not mechanisms.regression_passed(
        {"exit_code": 0, "collected": 1, "passed": 1, "skipped": 0, "selectors": ["x"]},
        ["x", "y"],
    )
    assert not mechanisms.regression_passed({"exit_code": 0}, ["x"])
