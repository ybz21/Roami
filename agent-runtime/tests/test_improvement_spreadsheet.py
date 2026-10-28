"""Workbook adapter checks without shipping benchmark inputs or reference answers."""

import io
import json
import zipfile

import pytest

from roami_agent.improvement.evaluation.benchmarks.spreadsheet import (
    cell_range,
    import_spreadsheet,
    same_cell_value,
)
from roami_agent.improvement.evaluation.contracts import agent_view
from roami_agent.improvement.evaluation.grading import judge_case
from roami_agent.protocol.errors import DomainError


def xlsx(*, value=None, merge=False, original="preserved", formula=False):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        cell = f'<c r="H10"><v>{value}</v></c>' if value is not None else ""
        if formula:
            cell = '<c r="H10"><f>1+2</f><v/></c>'
        merges = '<mergeCells><mergeCell ref="A1:B1"/></mergeCells>' if merge else ""
        original_cell = (
            f'<c r="A1"><v>{original}</v></c>'
            if type(original) in {int, float}
            else '<c r="A1" t="inlineStr"><is><t>' + original + "</t></is></c>"
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1">'
            + original_cell
            + '</row><row r="10">'
            + cell
            + "</row></sheetData>"
            + merges
            + "</worksheet>",
        )
    return buffer.getvalue()


def suite(tmp_path, original="preserved"):
    source, golden, metadata = (
        tmp_path / name for name in ("input.xlsx", "golden.xlsx", "metadata.json")
    )
    source.write_bytes(xlsx(merge=True, original=original))
    golden.write_bytes(xlsx(value=3, original=original))
    metadata.write_text(
        json.dumps(
            {
                "id": "fixture",
                "instruction": "Unmerge and count distinct items.",
                "answer_position": "H2:H24",
            }
        )
    )
    return import_spreadsheet(
        metadata, source, golden, revision="a" * 40, upstream_revision="b" * 40
    )


@pytest.mark.parametrize(
    "failure",
    [None, "wrong_value", "uncached_formula", "changed_input", "still_merged", "bad_archive"],
)
def test_workbook_saved_values_and_input_preservation(tmp_path, failure):
    case = suite(tmp_path)["cases"][0]
    output = tmp_path / "result.xlsx"
    output.write_bytes(
        xlsx(
            value=4 if failure == "wrong_value" else 3,
            original="changed" if failure == "changed_input" else "preserved",
            merge=failure == "still_merged",
            formula=failure == "uncached_formula",
        )
    )
    if failure == "bad_archive":
        output.write_bytes(b"not an XLSX")
    grade = judge_case(case, "", tmp_path)
    assert grade["passed"] == (failure is None)
    assert not grade["official_leaderboard_comparable"]
    assert "expected" not in json.dumps(agent_view(case, tmp_path))


def test_workbook_oracle_is_frozen_outside_editable_input(tmp_path):
    case = suite(tmp_path)["cases"][0]
    (tmp_path / "input.xlsx").write_bytes(xlsx(value=99))
    (tmp_path / "result.xlsx").write_bytes(xlsx(value=99))
    assert not judge_case(case, "", tmp_path)["passed"]


@pytest.mark.parametrize(
    "actual,expected,equal",
    [
        (0.4126388888888889, 0.412638888888889, True),
        (0.9000000000000005, 0.9, True),
        (0.412638888889889, 0.412638888888889, False),
        (0.0, 1e-20, False),
        (1, 1.0000000000000002, False),
        (1234567890123456, 1234567890123457, False),
        (True, 1, False),
        ("0.4126388888888889", "0.412638888888889", False),
        ("0.9", 0.9, False),
        (float("nan"), float("nan"), False),
        (float("inf"), float("inf"), False),
    ],
)
def test_fractional_cell_comparison_keeps_types_and_real_changes(actual, expected, equal):
    assert same_cell_value(actual, expected) is equal


@pytest.mark.parametrize("changed", [False, True])
def test_workbook_save_roundtrip_ignores_only_fractional_tail_bits(tmp_path, changed):
    case = suite(tmp_path, original=0.412638888888889)["cases"][0]
    (tmp_path / "result.xlsx").write_bytes(
        xlsx(value=3, original=0.412639 if changed else 0.4126388888888889)
    )
    grade = judge_case(case, "", tmp_path)
    assert grade["passed"] is not changed
    assert grade["checks"]["input_values_preserved"] is not changed
    assert "2e-15" in case["prompt"]
    assert case["origin"]["adapter_revision"] == "spreadsheet-values-v2-fractional-roundtrip"


@pytest.mark.parametrize(
    "value", ["A0:A1", "A1:XFD1048576", "XFE1:XFE2", "H24:H2", "A1", "../../file"]
)
def test_workbook_range_bounds(value):
    with pytest.raises(DomainError):
        cell_range(value)
