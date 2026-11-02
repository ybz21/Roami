"""Editable text, style preservation and publication guards over real PPTX files."""

import hashlib
import io
import json
import zipfile
from pathlib import Path

import presentation
import pytest
from deck_fixture import text_deck_bytes
from document_publication import PublicationError, Workspace
from jsonschema import ValidationError
from lxml import etree
from pptx import Presentation
from pptx_package import NS, PresentationError


@pytest.fixture
def text_document(tmp_path):
    contract = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "cases/case-64-mech-dp01/input/text-replacement.json"
        ).read_text()
    )
    source = tmp_path / "source.pptx"
    source.write_bytes(text_deck_bytes(contract["source_runs"]))
    request = {
        "path": "source.pptx",
        "expectedSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "destination": "edited.pptx",
        "expectedDestinationSha256": None,
        "operations": [
            {
                "slide": 1,
                "target": {"shapePath": [0]},
                "replaceText": contract["replacement"],
            }
        ],
    }
    return Workspace(tmp_path), source, request, contract


def rewrite_paragraph(source, request, transform):
    with zipfile.ZipFile(source) as package:
        parts = {name: package.read(name) for name in package.namelist()}
    root = etree.fromstring(parts["ppt/slides/slide1.xml"])
    transform(root.find("p:cSld/p:spTree/p:sp/p:txBody/a:p", NS))
    parts["ppt/slides/slide1.xml"] = etree.tostring(root)
    with zipfile.ZipFile(source, "w") as package:
        for name, body in parts.items():
            package.writestr(name, body)
    request["expectedSha256"] = hashlib.sha256(source.read_bytes()).hexdigest()


def test_cross_run_replacement_retains_editable_style_and_other_parts(text_document):
    workspace, source, request, contract = text_document
    original = source.read_bytes()
    result = presentation.edit(workspace, request)
    output = source.with_name("edited.pptx")
    assert result["changes"][0]["replaceText"] == {
        "old": contract["replacement"]["old"],
        "new": contract["replacement"]["new"],
        "occurrences": 1,
    }
    assert source.read_bytes() == original
    assert result["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    before, after = Presentation(io.BytesIO(original)), Presentation(output)
    assert after.slides[0].shapes[0].text == contract["expected_text"]
    assert after.slides[0].shapes[1].text == before.slides[0].shapes[1].text
    first = before.slides[0].shapes[0].text_frame.paragraphs[0]
    revised = after.slides[0].shapes[0].text_frame.paragraphs[0]
    assert first.alignment == revised.alignment
    assert [run._r.rPr.xml for run in first.runs] == [
        run._r.rPr.xml for run in revised.runs
    ]
    assert revised.runs[1].font.bold and revised.runs[2].font.italic
    with zipfile.ZipFile(io.BytesIO(original)) as old, zipfile.ZipFile(output) as new:
        assert old.namelist() == new.namelist()
        assert [
            name for name in old.namelist() if old.read(name) != new.read(name)
        ] == ["ppt/slides/slide1.xml"]
        old_root, new_root = (
            etree.fromstring(p.read("ppt/slides/slide1.xml")) for p in (old, new)
        )
        for root in (old_root, new_root):
            for node in root.findall("p:cSld/p:spTree/p:sp/p:txBody/a:p/a:r/a:t", NS):
                node.text = ""
                node.attrib.pop("{http://www.w3.org/XML/1998/namespace}space", None)
        assert etree.tostring(old_root) == etree.tostring(new_root)


@pytest.mark.parametrize("new", ["", " ", "中文 & <正文>", "revised\ttext"])
def test_removal_and_xml_text_remain_literal(text_document, new):
    workspace, source, request, _ = text_document
    request["operations"][0]["replaceText"]["new"] = new
    presentation.edit(workspace, request)
    assert (
        Presentation(source.with_name("edited.pptx")).slides[0].shapes[0].text
        == "增长摘要：" + new + "；已复核"
    )


@pytest.mark.parametrize("across_runs", [False, True])
def test_repeated_matches_are_explicit_and_replaced_backwards(
    text_document, across_runs
):
    workspace, source, request, _ = text_document
    runs = (
        [{"text": "aaaa"}]
        if not across_runs
        else [{"text": t} for t in ("a", "aa", "a")]
    )
    source.write_bytes(text_deck_bytes(runs))
    request["expectedSha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    replacement = request["operations"][0]["replaceText"] = {
        "old": "aa",
        "new": "中文长文本",
    }
    with pytest.raises(PresentationError, match="MATCH_COUNT_MISMATCH"):
        presentation.edit(workspace, request)
    assert not source.with_name("edited.pptx").exists()
    replacement["expectedCount"] = 2
    presentation.edit(workspace, request)
    assert (
        Presentation(source.with_name("edited.pptx")).slides[0].shapes[0].text
        == "中文长文本" * 2
    )


def test_sequential_replacements_can_share_an_object(text_document):
    workspace, source, request, _ = text_document
    request["operations"].append(
        {
            "slide": 1,
            "target": {"shapePath": [0]},
            "replaceText": {"old": "；已复核", "new": ""},
        }
    )
    presentation.edit(workspace, request)
    assert (
        Presentation(source.with_name("edited.pptx")).slides[0].shapes[0].text
        == "增长摘要：修订结论 <已核对 & 可编辑>"
    )


def test_match_count_covers_all_paragraphs_without_rebuilding_them(text_document):
    workspace, source, request, _ = text_document

    def transform(paragraph):
        import copy

        paragraph.addnext(copy.deepcopy(paragraph))

    rewrite_paragraph(source, request, transform)
    with pytest.raises(PresentationError, match="MATCH_COUNT_MISMATCH"):
        presentation.edit(workspace, request)
    request["operations"][0]["replaceText"]["expectedCount"] = 2
    presentation.edit(workspace, request)
    paragraphs = (
        Presentation(source.with_name("edited.pptx"))
        .slides[0]
        .shapes[0]
        .text_frame.paragraphs
    )
    assert len(paragraphs) == 2 and paragraphs[0].text == paragraphs[1].text
    assert all("旧版结论" not in paragraph.text for paragraph in paragraphs)


def test_field_matches_are_not_silently_ignored(text_document):
    workspace, source, request, _ = text_document

    def transform(paragraph):
        field = etree.SubElement(paragraph, "{" + NS["a"] + "}fld")
        etree.SubElement(field, "{" + NS["a"] + "}t").text = "旧版结论"

    rewrite_paragraph(source, request, transform)
    with pytest.raises(PresentationError, match="UNSUPPORTED"):
        presentation.edit(workspace, request)
    assert not source.with_name("edited.pptx").exists()


@pytest.mark.parametrize(
    "old,new",
    [
        ("不存在", "new"),
        ("旧版结论", "bad\nline"),
        ("旧版结论", "bad\rline"),
        ("旧版结论", "bad\0text"),
        ("旧版结论", "bad\ud800text"),
    ],
)
def test_missing_or_unsupported_text_publishes_nothing(text_document, old, new):
    workspace, source, request, _ = text_document
    request["operations"][0]["replaceText"] = {"old": old, "new": new}
    with pytest.raises(PresentationError):
        presentation.edit(workspace, request)
    assert not source.with_name("edited.pptx").exists()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == request["expectedSha256"]


@pytest.mark.parametrize("boundary", ["field", "break", "unknown"])
def test_inline_boundaries_cannot_be_flattened(text_document, boundary):
    workspace, source, request, _ = text_document

    def transform(paragraph):
        run = paragraph.findall("a:r", NS)[2]
        if boundary == "field":
            run.tag = "{" + NS["a"] + "}fld"
            run.set("id", "{00000000-0000-0000-0000-000000000001}")
            run.set("type", "slidenum")
        else:
            paragraph.insert(
                paragraph.index(run),
                etree.Element(
                    "{"
                    + NS["a"]
                    + "}"
                    + ("br" if boundary == "break" else "unsupported")
                ),
            )

    rewrite_paragraph(source, request, transform)
    with pytest.raises(PresentationError):
        presentation.edit(workspace, request)
    assert not source.with_name("edited.pptx").exists()


def test_later_text_failure_never_publishes_partial_batch(text_document):
    workspace, source, request, _ = text_document
    request["operations"].append(
        {
            "slide": 1,
            "target": {"shapePath": [0]},
            "replaceText": {"old": "missing", "new": "changed"},
        }
    )
    with pytest.raises(PresentationError, match="MATCH_COUNT_MISMATCH"):
        presentation.edit(workspace, request)
    assert not source.with_name("edited.pptx").exists()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == request["expectedSha256"]


@pytest.mark.parametrize(
    "replacement",
    [
        {"old": "", "new": "x"},
        {"old": "x"},
        {"old": "x", "new": "y", "expectedCount": 0},
        {"old": "x", "new": "y", "expectedCount": True},
        {"old": "x", "new": "y", "regex": True},
    ],
)
def test_invalid_text_request_is_rejected(text_document, replacement):
    workspace, source, request, _ = text_document
    request["operations"][0]["replaceText"] = replacement
    with pytest.raises(ValidationError):
        presentation.edit(workspace, request)
    assert not source.with_name("edited.pptx").exists()


@pytest.mark.parametrize("changed", ["source", "destination"])
def test_text_replacement_keeps_source_and_destination_guards(text_document, changed):
    workspace, source, request, _ = text_document
    path = source if changed == "source" else source.with_name("edited.pptx")
    path.write_bytes(b"concurrent user change")
    with pytest.raises(PublicationError, match="CHANGED"):
        presentation.edit(workspace, request)
    assert path.read_bytes() == b"concurrent user change"
