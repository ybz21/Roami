"""Incomplete or substituted recovery receipts cannot pass an RSI Case."""

import json
import runpy
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


@pytest.fixture
def runner():
    return runpy.run_path(str(Path(__file__).parents[3] / "scripts/dev/run-task-recovery-cases.py"))


@pytest.mark.parametrize(
    "fault", [None, "missing", "duplicate", "skipped", "failure", "error", "wrong"]
)
def test_python_receipt_requires_all_original_cases_without_skips(tmp_path, runner, fault):
    suite = ET.Element("testsuite")
    names = ["test_send[image]", "test_send[file]"]
    if fault == "missing":
        names.pop()
    elif fault == "duplicate":
        names[1] = names[0]
    elif fault == "wrong":
        names[1] = "test_other"
    for name in names:
        case = ET.SubElement(suite, "testcase", classname="tests.test_original_session", name=name)
        if fault in {"skipped", "failure", "error"}:
            ET.SubElement(case, fault)
    path = tmp_path / "junit.xml"
    ET.ElementTree(suite).write(path)
    result = runner["pytest_receipt"](
        path,
        [
            "tests/test_original_session.py::test_send[image]",
            "tests/test_original_session.py::test_send[file]",
        ],
    )
    assert result["passed"] is (fault is None)


@pytest.mark.parametrize("fault", [None, "missing", "duplicate", "skip", "fail", "no_package"])
def test_go_receipt_requires_each_run_and_pass_and_package_completion(tmp_path, runner, fault):
    names = ["TestCancellation", "TestCancellation/codex", "TestCancellation/claude"]
    events = [{"Action": "run", "Test": name} for name in names]
    passed = list(names)
    if fault == "missing":
        passed.pop()
    elif fault == "duplicate":
        passed[2] = passed[1]
    events += [{"Action": "pass", "Test": name} for name in passed]
    if fault in {"skip", "fail"}:
        events.append({"Action": fault, "Test": names[-1]})
    if fault != "no_package":
        events.append({"Action": "pass", "Package": "recovery"})
    path = tmp_path / "go.jsonl"
    path.write_text("\n".join(json.dumps(event) for event in events))
    result = runner["go_receipt"](path, names)
    assert result["passed"] is (fault is None)


def test_missing_or_malformed_receipts_are_never_treated_as_empty_success(tmp_path, runner):
    path = tmp_path / "receipt"
    with pytest.raises(FileNotFoundError):
        runner["pytest_receipt"](path, [])
    path.write_text("not a structured event")
    with pytest.raises(ValueError):
        runner["go_receipt"](path, ["TestCancellation"])


def test_recovery_cases_publish_frozen_selection_and_preserve_historical_suite():
    from roami_agent.improvement.evaluation.case_catalog import case_definitions, case_resource
    from roami_agent.improvement.evaluation.corpus import authored_suite

    definitions = {case["id"]: case for case in case_definitions()}
    all_ids = []
    for ident in ["MECH-TF01", "MECH-SI01", "MECH-TC01"]:
        case = definitions[ident]
        assert case["selected_in_mixed_suite_v1"] is False
        assert case["kind"] == "mechanism_regression" and case["counts_as_delivery"] is False
        manifest = json.loads(case_resource(ident, "input/scenarios.json").read_text())
        assert manifest["case_id"] == ident and manifest["expected_pytest_ids"]
        all_ids.extend(manifest["expected_pytest_ids"])
    assert len(all_ids) == len(set(all_ids))
    assert len(authored_suite("task-recovery-cases")["cases"]) == 40
