"""The public-course task retains its full table and requires every counterexample."""

import json

import pytest

from roami_agent.improvement.evaluation.benchmarks.gaia_tasks import (
    TASK_ID,
    grade_gaia_course,
    import_gaia_course,
)
from roami_agent.improvement.evaluation.contracts import agent_view
from roami_agent.improvement.integrations.artifact_files import materialize
from roami_agent.protocol.errors import DomainError

QUESTION = """Given this table defining * on S = {a, b, c, d, e}
|*|a|b|c|d|e|
|---|---|---|---|---|---|
|a|a|b|c|b|d|
|b|b|c|a|e|c|
|c|c|a|b|b|a|
|d|b|e|b|e|d|
|e|d|b|a|d|c|
Return the subset involved in any counterexamples to commutativity in alphabetical order.
"""
EXPECTED = [{"left": "b", "right": "e", "left_then_right": "c", "right_then_left": "b"}]


def case_file(tmp_path):
    source = tmp_path / "public-course.json"
    source.write_text(
        json.dumps([{"task_id": TASK_ID, "Level": "1", "file_name": "", "question": QUESTION}])
    )
    return source


def test_complete_source_table_and_derived_proof_are_frozen_separately(tmp_path):
    suite = import_gaia_course(case_file(tmp_path))
    case = suite["cases"][0]
    assert case["files"]["question.md"] == QUESTION
    assert case["judge"]["counterexamples"] == EXPECTED
    assert case["judge"]["affected"] == ["b", "e"]
    assert len(case["origin"]["revision"]) == 64
    view = agent_view(case, tmp_path)
    assert "judge" not in view and "affected" not in json.dumps(view)
    assert suite["official_leaderboard_comparable"] is False


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "wrong_answer",
        "wrong_order",
        "missing_pair",
        "duplicate_pair",
        "wrong_value",
        "changed_input",
    ],
)
def test_answer_and_entire_proof_must_agree_with_unchanged_table(tmp_path, fault):
    case = import_gaia_course(case_file(tmp_path))["cases"][0]
    work = tmp_path / "work"
    materialize(case, work)
    answer = "b, e"
    proof = json.loads(json.dumps(EXPECTED))
    if fault == "wrong_answer":
        answer = "a, e"
    if fault == "wrong_order":
        answer = "e, b"
    if fault == "missing_pair":
        proof = []
    if fault == "duplicate_pair":
        proof *= 2
    if fault == "wrong_value":
        proof[0]["left_then_right"] = "b"
    if fault == "changed_input":
        (work / "question.md").write_text(QUESTION.replace("|b|b|c|a|e|c|", "|b|b|c|a|e|b|"))
    (work / "answer.txt").write_text(answer)
    (work / "counterexamples.json").write_text(json.dumps(proof))
    grade = grade_gaia_course(case, work)
    assert grade["passed"] is (fault is None)
    if fault in {"missing_pair", "duplicate_pair", "wrong_value"}:
        assert grade["native_metric"] == 1 and not grade["checks"]["complete_counterexamples"]


def test_import_rejects_missing_or_duplicate_public_task_ids(tmp_path):
    source = case_file(tmp_path)
    records = json.loads(source.read_text())
    for rows in [[], records * 2]:
        source.write_text(json.dumps(rows))
        with pytest.raises(DomainError, match="SOURCE_TASK_REQUIRED"):
            import_gaia_course(source)
