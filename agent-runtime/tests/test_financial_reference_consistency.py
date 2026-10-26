"""Conflicting public annotations do not become hidden numeric acceptance targets."""

import json

import pytest

from roami_agent.improvement.contracts import agent_view
from roami_agent.improvement.sampling import import_finqa
from roami_agent.protocol.errors import DomainError


def financial_record(identifier, answer, execution_answer):
    return {
        "id": identifier,
        "pre_text": ["A supplied report."],
        "table": [["year", "value"]],
        "post_text": [],
        "qa": {
            "question": "What is the requested value?",
            "answer": answer,
            "exe_ans": execution_answer,
            "program": "hidden_reference_program",
        },
    }


def test_inconsistent_annotations_are_excluded_before_sampling_without_rewriting_answers(tmp_path):
    records = [
        financial_record("rounded", "215.33", 646 / 3),
        financial_record("percentage", "53.8%", 0.538),
        financial_record("exact", "17", 17),
        financial_record("conflict", "215.33", 324.5),
        financial_record("unverifiable", "a narrative answer", 42),
    ]
    path = tmp_path / "dev.json"
    path.write_text(json.dumps(records))
    before = path.read_bytes()
    suite = import_finqa(path, revision="a" * 40, source_split="dev", count=3)
    assert len(suite["cases"]) == 3 and suite["sampling_lock"]["eligible_records"] == 3
    assert {c["origin"]["task_id"] for c in suite["cases"]} == {"rounded", "percentage", "exact"}
    excluded = {r["id"]: r["reason"] for r in suite["sampling_lock"]["excluded"]}
    assert excluded == {
        "conflict": "inconsistent_displayed_execution_answer",
        "unverifiable": "unsupported_displayed_numeric_answer",
    }
    expected = {r["id"]: r["qa"]["exe_ans"] for r in records}
    for case in suite["cases"]:
        assert case["judge"]["expected"] == expected[case["origin"]["task_id"]]
        assert "hidden_reference_program" not in json.dumps(agent_view(case, tmp_path))
        assert "0.0001" in case["prompt"]
        assert case["origin"]["adapter_revision"] == "financial-numeric-v2-consistent-reference"
    assert path.read_bytes() == before
    assert suite["id"] == "finqa-sample-v2"
    assert (
        import_finqa(path, revision="a" * 40, source_split="dev", count=3)["content_hash"]
        == suite["content_hash"]
    )


def test_invalid_references_cannot_silently_reduce_the_requested_sample_count(tmp_path):
    path = tmp_path / "dev.json"
    path.write_text(json.dumps([financial_record("good", "1", 1), financial_record("bad", "2", 9)]))
    with pytest.raises(DomainError, match="RSI_SAMPLE_COUNT"):
        import_finqa(path, revision="a" * 40, source_split="dev", count=2)


@pytest.mark.parametrize(
    "answer,expected,accepted",
    [
        ("12,345.60", 12345.6, True),
        ("1.25e3", 1250, True),
        ("0.10%", 0.001, True),
        ("0.538", -0.538, False),
        ("12,34", 1234, False),
        ("1e1000000", 1, False),
        ("215.33 million", 215.33, False),
        (True, 1, False),
        (None, 1, False),
    ],
)
def test_reference_formats_and_percent_units_are_unambiguous(tmp_path, answer, expected, accepted):
    path = tmp_path / "dev.json"
    path.write_text(json.dumps([financial_record("sample", answer, expected)]))
    if accepted:
        suite = import_finqa(path, revision="a" * 40, source_split="dev", count=1)
        assert suite["cases"][0]["judge"]["expected"] == expected
    else:
        with pytest.raises(DomainError, match="RSI_SAMPLE_COUNT"):
            import_finqa(path, revision="a" * 40, source_split="dev", count=1)
