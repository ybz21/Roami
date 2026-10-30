"""Inspection remains an optional package capability with source and scope checks."""

import hashlib
import io
import json
import zipfile

import office_palette as office_palettes
import pytest
from document_publication import Workspace
from pptx_package import presentation_metadata
from presentation import inspect, main
from presentation_fixture import presentation_bytes


def test_grouped_text_and_empty_decorations_have_distinct_locators():
    document = presentation_metadata(presentation_bytes())
    slide = document["slides"][0]
    assert document["rendered"] is False
    assert slide["emptyTextFramePaths"] == [[0]]
    assert [x["text"] for x in slide["textObjects"]] == ["正文", "Heading"]
    assert [x["ordinal"] for x in slide["textObjects"]] == [1, 2]
    assert [x["shapePath"] for x in slide["textObjects"]] == [[1, 0], [2]]
    assert slide["textObjects"][0]["paragraphs"][0]["alignment"] == "center"


def test_unavailable_editor_palette_does_not_invent_color_values(tmp_path, monkeypatch):
    monkeypatch.setattr(office_palettes, "PALETTES", (tmp_path / "absent.soc",))
    assert office_palettes.installed_presentation_palette() is None


def test_excessive_nested_groups_fail_without_exhausting_the_parser_stack():
    with zipfile.ZipFile(io.BytesIO(presentation_bytes())) as source:
        parts = {name: source.read(name) for name in source.namelist()}
    slide = parts["ppt/slides/slide1.xml"].decode()
    slide = slide.replace("<p:spTree>", "<p:spTree>" + "<p:grpSp>" * 66)
    slide = slide.replace("</p:spTree>", "</p:grpSp>" * 66 + "</p:spTree>")
    parts["ppt/slides/slide1.xml"] = slide.encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as package:
        for name, body in parts.items():
            package.writestr(name, body)
    with pytest.raises(ValueError, match="group depth"):
        presentation_metadata(output.getvalue())


def test_text_color_keeps_transforms_instead_of_claiming_the_base_rgb_is_final():
    from xml.etree import ElementTree

    from pptx_package import NS, text_color

    properties = ElementTree.fromstring(
        '<a:rPr xmlns:a="' + NS["a"] + '"><a:solidFill><a:srgbClr val="12AB34">'
        '<a:tint val="50000"/></a:srgbClr></a:solidFill></a:rPr>'
    )
    assert text_color(properties) == {
        "kind": "srgbClr",
        "value": "12AB34",
        "transforms": [{"kind": "tint", "val": "50000"}],
    }
    assert text_color(None) is None


def test_inspection_hash_identifies_original_bytes_without_mutation(
    tmp_path, monkeypatch
):
    path = tmp_path / "deck.pptx"
    body = presentation_bytes()
    path.write_bytes(body)
    palette = tmp_path / "standard.soc"
    palette.write_text(
        '<colors xmlns:draw="urn:palette"><color draw:name="Example" draw:color="#12ab34"/></colors>'
    )
    monkeypatch.setattr(office_palettes, "PALETTES", (palette,))
    result = inspect(Workspace(tmp_path), path.name)
    assert result["sha256"] == hashlib.sha256(body).hexdigest()
    assert result["sourceSizeBytes"] == len(body)
    assert result["editorPalette"]["colors"] == {"Example": "#12AB34"}
    assert result["slides"][0]["textObjects"][0]["shapePath"] == [1, 0]
    assert path.read_bytes() == body


@pytest.mark.parametrize("kind", ["outside", "symlink"])
def test_inspection_never_leaks_files_outside_workspace(tmp_path, capsys, kind):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "private.pptx"
    body = presentation_bytes()
    outside.write_bytes(body)
    path = outside
    if kind == "symlink":
        path = workspace / "link.pptx"
        path.symlink_to(outside)
    assert main(["inspect", "--workspace", str(workspace), "--path", str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    assert outside.read_bytes() == body


@pytest.mark.parametrize("corruption", ["not_zip", "external_slide", "xml_entity"])
def test_untrusted_packages_fail_before_publication(tmp_path, capsys, corruption):
    body = presentation_bytes()
    if corruption == "not_zip":
        body = b"not a presentation"
    else:
        with zipfile.ZipFile(io.BytesIO(body)) as package:
            parts = {name: package.read(name) for name in package.namelist()}
        if corruption == "external_slide":
            parts["ppt/_rels/presentation.xml.rels"] = (
                b'<Relationships><Relationship Id="slide" TargetMode="External" Target="https://must-not-fetch.invalid/private"/></Relationships>'
            )
        else:
            parts["ppt/slides/slide1.xml"] = (
                b'<!DOCTYPE x [<!ENTITY x "unsafe">]><x>&x;</x>'
            )
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as package:
            for name, data in parts.items():
                package.writestr(name, data)
        body = stream.getvalue()
    path = tmp_path / "deck.pptx"
    path.write_bytes(body)
    assert main(["inspect", "--workspace", str(tmp_path), "--path", path.name]) == 1
    assert json.loads(capsys.readouterr().out)["writePublished"] is False
    assert path.read_bytes() == body
