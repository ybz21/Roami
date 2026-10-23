import json
import zipfile

import pytest

from roami_agent.improvement.contracts import agent_view
from roami_agent.improvement.data_analysis import import_data_analysis
from roami_agent.improvement.grading import judge_case
from roami_agent.protocol.errors import DomainError


def source_pack(tmp_path, *, extra=None):
    metadata = tmp_path / "data.json"
    metadata.write_text(
        json.dumps(
            {
                "id": "00000001",
                "questions": ["question1"],
                "answers": ["SECRET_ANSWER_NOT_IN_INPUT"],
            }
        )
        + "\n"
    )
    archive = tmp_path / "data.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("data/00000001/introduction.txt", "Frozen scenario introduction")
        bundle.writestr(
            "data/00000001/question1.txt", "Answer the selected question using the workbook."
        )
        bundle.writestr("data/00000001/input.xlsx", b"fixture asset only")
        if extra:
            bundle.writestr(extra, "untrusted")
    return metadata, archive


def test_workbook_question_adapter_keeps_answer_key_outside_inputs(tmp_path):
    metadata, archive = source_pack(tmp_path)
    suite = import_data_analysis(
        metadata,
        archive,
        group_id="00000001",
        question_id="question1",
        revision="a" * 40,
        upstream_revision="b" * 40,
    )
    case = suite["cases"][0]
    assert "SECRET_ANSWER" not in json.dumps(
        {"view": agent_view(case, tmp_path), "files": case["files"], "assets": case["asset_files"]}
    )
    (tmp_path / "result.json").write_text(json.dumps("SECRET_ANSWER_NOT_IN_INPUT"))
    assert judge_case(case, "", tmp_path)["passed"]
    (tmp_path / "result.json").write_text('"wrong"')
    assert not judge_case(case, "", tmp_path)["passed"]
    assert case["origin"]["adapted"] and not suite["official_leaderboard_comparable"]


def test_question_archive_traversal_is_rejected(tmp_path):
    metadata, archive = source_pack(tmp_path, extra="data/00000001/../outside.txt")
    with pytest.raises(DomainError):
        import_data_analysis(
            metadata,
            archive,
            group_id="00000001",
            question_id="question1",
            revision="a" * 40,
            upstream_revision="b" * 40,
        )
