"""Complete-history admission, frozen-input integrity and misleading answer rejection."""

import gzip
import hashlib
import json
import sys

import pytest

from roami_agent.improvement.evaluation.benchmarks.long_memory import (
    EVAL_SPEC,
    QUESTION_ID,
    grade_long_memory,
    import_long_memory,
    prepare_history,
)
from roami_agent.improvement.evaluation.contracts import agent_view
from roami_agent.improvement.integrations.artifact_files import materialize
from roami_agent.protocol.errors import DomainError

METRIC = r"""
import re

def extract_boxed_answer(text):
    return text.rsplit('\\boxed{',1)[-1].rstrip('}').strip()

def normalize_phrase(text):
    return ' '.join(re.sub(r'[^\w\s]', '', re.sub('[,;]', ' ', text.lower())).split())

def eval_from_spec(spec, prediction, expected):
    return all(phrase in normalize_phrase(prediction).split() for phrase in normalize_phrase(expected).split())
"""


def source_files(tmp_path, tree=None):
    ids = [f"{i:08x}" for i in range(100)]
    paths = {
        name: tmp_path / (name + ".json")
        for name in ["questions", "haystacks", "trajectories", "verifier"]
    }
    paths["questions"].write_text(
        json.dumps(
            {
                "id": QUESTION_ID,
                "question": "Recall the form affordance from prior history.",
                "image": None,
                "answer": "One; User",
                "eval_function": EVAL_SPEC,
            }
        )
        + "\n"
    )
    paths["haystacks"].write_text(json.dumps({QUESTION_ID: ids}))
    paths["trajectories"].write_text(
        "".join(
            json.dumps(
                {
                    "id": i,
                    "domain": "enterprise",
                    "goal": "Open the form",
                    "states": [
                        {
                            "state_index": 0,
                            "accessibility_tree": tree
                            or "RootWebArea 'New Record | User | ServiceNow'\n\tbutton 'Send an email to this address', visible",
                            "action": None,
                            "screenshot": "unavailable.png",
                        }
                    ],
                }
            )
            + "\n"
            for i in reversed(ids)
        )
    )
    paths["verifier"].write_text(METRIC)
    return paths


def imported(paths):
    return import_long_memory(**paths, revision="a" * 40, code_revision="b" * 40)


class LocalGrader:
    async def sandbox(self, workspace, program, *, input, timeout):
        import asyncio

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            program.replace("'/workspace'", repr(str(workspace))),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, error = await asyncio.wait_for(process.communicate(input), timeout)
        assert process.returncode == 0, error.decode()
        return out


def prepared(tmp_path, tree=None):
    paths = source_files(tmp_path, tree)
    case = imported(paths)["cases"][0]
    work = tmp_path / "work"
    materialize(case, work)
    prepare_history(case, work)
    (work / "answer.txt").write_text(r"\boxed{One; User}")
    (work / "evidence.json").write_text(
        json.dumps(
            [
                {
                    "trajectory_id": "00000000",
                    "state_index": 0,
                    "quote": "Send an email to this address",
                }
            ]
        )
    )
    return case, work


@pytest.mark.parametrize(
    "tree,expected",
    [
        (
            (
                "RootWebArea 'Classic | Unified Navigation App | ServiceNow'\n"
                "\t[a] Iframe 'Main Content', visible\n"
                "\t\tRootWebArea 'New Record | User | ServiceNow'\n"
                "\t\t\t[a321] button 'Send an email to this address', visible"
            ),
            True,
        ),
        (
            (
                "RootWebArea 'New Record | User | ServiceNow'\n"
                "\tRootWebArea 'New Record | Incident | ServiceNow'\n"
                "\t\tbutton 'Send an email to this address', visible"
            ),
            False,
        ),
        (
            (
                "RootWebArea 'Classic | Unified Navigation App | ServiceNow'\n"
                "\tRootWebArea 'New Record | User | ServiceNow'\n"
                "\t\theading 'User New record'\n"
                "\tRootWebArea 'New Record | Incident | ServiceNow'\n"
                "\t\tbutton 'Send an email to this address', visible"
            ),
            False,
        ),
        (
            (
                "RootWebArea 'New Record | Incident | ServiceNow'\n"
                "\tStaticText 'User'\n"
                "\tbutton 'Send an email to this address', visible"
            ),
            False,
        ),
    ],
)
async def test_email_citation_uses_its_nested_document_not_the_navigation_title(
    tmp_path, tree, expected
):
    case, work = prepared(tmp_path, tree)
    grade = await grade_long_memory(case, work, LocalGrader())
    assert grade["checks"]["valid_source_citations"]
    assert grade["checks"]["cited_affordance"] is expected
    assert grade["passed"] is expected


def test_import_preserves_all_hundred_in_original_order_without_exposing_oracle(tmp_path):
    case, work = prepared(tmp_path)
    assert len(list((work / "history").iterdir())) == 100
    assert json.loads((work / "history-index.json").read_text())["trajectory_ids"] == [
        f"{i:08x}" for i in range(100)
    ]
    assert not list(work.glob("*.part"))
    assert "One; User" not in json.dumps(agent_view(case, work))
    assert case["judge"]["verifier"] not in json.dumps(agent_view(case, work))
    assert "static-environment" in case["cluster"]


@pytest.mark.parametrize("fault", ["missing_id", "duplicate_id", "missing_trajectory"])
def test_import_rejects_history_reduction_or_duplicate_source_ids(tmp_path, fault):
    paths = source_files(tmp_path)
    if fault == "missing_trajectory":
        lines = paths["trajectories"].read_text().splitlines()
        paths["trajectories"].write_text("\n".join(lines[:-1]) + "\n")
    else:
        data = json.loads(paths["haystacks"].read_text())
        if fault == "missing_id":
            data[QUESTION_ID].pop()
        else:
            data[QUESTION_ID][-1] = data[QUESTION_ID][0]
        paths["haystacks"].write_text(json.dumps(data))
    with pytest.raises(DomainError, match="FULL_HISTORY_REQUIRED"):
        imported(paths)


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "wrong_answer",
        "extra_forms",
        "missing_evidence",
        "invented_quote",
        "invalid_state",
        "changed_history",
        "changed_index",
        "extra_history",
    ],
)
async def test_native_metric_and_independent_integrity_gates(tmp_path, fault):
    case, work = prepared(tmp_path)
    if fault == "wrong_answer":
        (work / "answer.txt").write_text(r"\boxed{Two; Incident}")
    if fault == "extra_forms":
        (work / "answer.txt").write_text(r"\boxed{One; User; Incident}")
    if fault == "missing_evidence":
        (work / "evidence.json").write_text("[]")
    if fault in {"invented_quote", "invalid_state"}:
        evidence = json.loads((work / "evidence.json").read_text())
        if fault == "invented_quote":
            evidence[0]["quote"] = "Fabricated source text with no original support."
        else:
            evidence[0]["state_index"] = True
        (work / "evidence.json").write_text(json.dumps(evidence))
    if fault == "changed_history":
        (work / "history/00000000.json").write_text("{}")
    if fault == "changed_index":
        (work / "history-index.json").write_text('{"trajectory_ids":[]}')
    if fault == "extra_history":
        (work / "history/extra.json").write_text("{}")
    grade = await grade_long_memory(case, work, LocalGrader())
    assert grade["passed"] is (fault is None)
    if fault == "extra_forms":
        assert grade["native_metric"] == 1
        assert grade["checks"]["exact_final_phrases"] is False
    if fault == "changed_history":
        assert grade["checks"]["history_unchanged"] is False


def test_prepare_rejects_archive_content_with_a_recomputed_outer_hash(tmp_path):
    paths = source_files(tmp_path)
    case = imported(paths)["cases"][0]
    altered = gzip.compress(json.dumps([{"id": f"{i:08x}"} for i in range(100)]).encode(), mtime=0)
    import base64

    case["asset_files"] = {"history-000.part": base64.b64encode(altered).decode()}
    case["judge"]["packed_sha256"] = hashlib.sha256(altered).hexdigest()
    work = tmp_path / "work"
    materialize(case, work)
    with pytest.raises(DomainError, match="SOURCE_CHANGED"):
        prepare_history(case, work)


@pytest.mark.parametrize(
    ("answer", "passed"),
    [
        (r"\boxed{One; User form}", True),
        (r"\boxed{one: User forms}", True),
        (r"\boxed{One; User; Incident form}", False),
        (r"\boxed{Two; User form}", False),
        (r"\boxed{One; form}", False),
    ],
)
async def test_form_qualifiers_do_not_count_as_additional_answers(tmp_path, answer, passed):
    case, work = prepared(tmp_path)
    (work / "answer.txt").write_text(answer)
    grade = await grade_long_memory(case, work, LocalGrader())
    assert grade["hard_passed"] is passed
    assert grade["checks"]["valid_source_citations"]
    assert grade["checks"]["history_unchanged"]
    if passed:
        assert grade["checks"]["native_metric"]
