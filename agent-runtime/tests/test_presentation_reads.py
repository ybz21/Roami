"""Production read capability inspects documents without changing their bytes or scope."""

import base64
import hashlib
import io
import json
import zipfile

import pytest
from test_foundations import call
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.documents import office_palettes
from roami_agent.documents.presentation import presentation_metadata
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.storage.workspace_files import WorkspaceFiles
from roami_agent.tools.workspace_presentations import WorkspacePresentationReads


def presentation_bytes():
    ns = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
    ns += 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    ns += 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    parts = {
        "ppt/presentation.xml": f'<p:presentation {ns}><p:sldIdLst><p:sldId r:id="slide"/></p:sldIdLst></p:presentation>',
        "ppt/_rels/presentation.xml.rels": '<Relationships><Relationship Id="slide" Target="slides/slide1.xml"/></Relationships>',
        "ppt/slides/slide1.xml": f"""<p:sld {ns}><p:cSld><p:spTree>
          <p:sp><p:nvSpPr><p:cNvPr id="1" name="decoration"/></p:nvSpPr><p:txBody><a:p/></p:txBody></p:sp>
          <p:grpSp><p:nvGrpSpPr/><p:grpSpPr/>
            <p:sp><p:nvSpPr><p:cNvPr id="3" name="body"/></p:nvSpPr>
              <p:txBody><a:p><a:pPr algn="ctr"/><a:r><a:t>正文</a:t></a:r></a:p></p:txBody></p:sp>
          </p:grpSp>
          <p:sp><p:nvSpPr><p:cNvPr id="4" name="heading"/></p:nvSpPr>
            <p:txBody><a:p><a:r><a:t>Heading</a:t></a:r></a:p></p:txBody></p:sp>
        </p:spTree></p:cSld></p:sld>""",
    }
    body = io.BytesIO()
    with zipfile.ZipFile(body, "w") as bundle:
        for name, text in parts.items():
            bundle.writestr(name, text)
    return body.getvalue()


@pytest.fixture
def editor_palette(tmp_path, monkeypatch):
    path = tmp_path / "standard.soc"
    path.write_text(
        '<colors xmlns:draw="urn:palette"><color draw:name="Example" draw:color="#12ab34"/></colors>'
    )
    monkeypatch.setattr(office_palettes, "PALETTES", (path,))
    return path


def test_grouped_text_and_empty_decorations_have_distinct_locators():
    document = presentation_metadata(presentation_bytes())
    slide = document["slides"][0]
    assert document["rendered"] is False
    assert slide["emptyTextFramePaths"] == [[0]]
    assert [x["text"] for x in slide["textObjects"]] == ["正文", "Heading"]
    assert [x["ordinal"] for x in slide["textObjects"]] == [1, 2]
    assert [x["shapePath"] for x in slide["textObjects"]] == [[1, 0], [2]]
    assert slide["textObjects"][0]["paragraphs"][0]["alignment"] == "center"


async def test_document_pages_keep_original_hash_and_preserve_raw_reads(tmp_path, editor_palette):
    body = presentation_bytes()
    path = tmp_path / "deck.pptx"
    path.write_bytes(body)
    files = WorkspaceFiles(Settings())
    reader = WorkspacePresentationReads(files, files.read)
    binding = {"taskId": "task", "workspace": {"directory": str(tmp_path)}}
    try:
        raw = await reader.read({"path": "deck.pptx"}, binding)
        assert raw["sha256"] == hashlib.sha256(body).hexdigest()
        raw_bytes = (
            base64.b64decode(raw["data"]) if raw["encoding"] == "base64" else raw["data"].encode()
        )
        assert raw_bytes == body
        offset, chunks, hashes = 0, [], set()
        while True:
            result = await reader.read(
                {"path": "deck.pptx", "view": "document", "limit": 37, "offset": offset}, binding
            )
            chunks.append(
                base64.b64decode(result["data"])
                if result["encoding"] == "base64"
                else result["data"].encode()
            )
            hashes.add(result["viewSha256"])
            assert result["sha256"] == raw["sha256"] and result["sourceSizeBytes"] == len(body)
            if result["nextOffset"] is None:
                break
            offset = result["nextOffset"]
        document = json.loads(b"".join(chunks))
        assert len(hashes) == 1 and document["editorPalette"]["colors"] == {"Example": "#12AB34"}
        assert path.read_bytes() == body
    finally:
        await files.close()


@pytest.mark.parametrize("kind", ["outside", "symlink"])
async def test_document_view_keeps_the_workspace_boundary(tmp_path, kind, editor_palette):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret.pptx"
    outside.write_bytes(presentation_bytes())
    path = outside
    if kind == "symlink":
        path = workspace / "linked.pptx"
        path.symlink_to(outside)
    files = WorkspaceFiles(Settings())
    try:
        with pytest.raises(DomainError):
            await WorkspacePresentationReads(files, files.read).read(
                {"path": str(path), "view": "document"},
                {"taskId": "task", "workspace": {"directory": str(workspace)}},
            )
    finally:
        await files.close()


async def test_document_snapshot_change_is_not_reported_as_the_old_source(tmp_path, monkeypatch):
    path = tmp_path / "deck.pptx"
    path.write_bytes(presentation_bytes())
    files = WorkspaceFiles(Settings())

    async def changed(*args, **kwargs):
        return b"different bytes"

    monkeypatch.setattr(files, "snapshot", changed)
    try:
        with pytest.raises(DomainError, match="FILE_CHANGED"):
            await WorkspacePresentationReads(files, files.read).read(
                {"path": str(path), "view": "document"},
                {"taskId": "task", "workspace": {"directory": str(tmp_path)}},
            )
    finally:
        await files.close()


async def test_registered_read_and_discovery_offer_presentation_capability(
    store, tmp_path, editor_palette
):
    path = tmp_path / "deck.pptx"
    path.write_bytes(presentation_bytes())
    runtime = Runtime(store, ConversationModel(), settings=Settings(shell_roots=(tmp_path,)))
    try:
        assert any(
            x["name"] == "presentation_files"
            for x in runtime.tools.directory.list("幻灯片", "skill")["items"]
        )
        result = await runtime.tools.invoke(
            call("read", {"path": str(path), "view": "document"}), "main", {}
        )
        document = json.loads(result["data"])
        assert document["slides"][0]["textObjects"][0]["shapePath"] == [1, 0]
        assert result["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    finally:
        await runtime.close()


@pytest.mark.parametrize("corruption", ["not_zip", "external_slide", "xml_entity"])
async def test_untrusted_presentation_payloads_fail_as_document_errors(tmp_path, corruption):
    body = presentation_bytes()
    if corruption == "not_zip":
        body = b"not a presentation"
    else:
        parts = {}
        with zipfile.ZipFile(io.BytesIO(body)) as package:
            parts = {name: package.read(name) for name in package.namelist()}
        if corruption == "external_slide":
            parts["ppt/_rels/presentation.xml.rels"] = (
                b'<Relationships><Relationship Id="slide" TargetMode="External" '
                b'Target="https://must-not-fetch.invalid/private"/></Relationships>'
            )
        else:
            parts["ppt/slides/slide1.xml"] = b'<!DOCTYPE x [<!ENTITY x "unsafe">]><x>&x;</x>'
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as package:
            for name, value in parts.items():
                package.writestr(name, value)
        body = output.getvalue()
    path = tmp_path / "deck.pptx"
    path.write_bytes(body)
    files = WorkspaceFiles(Settings())
    try:
        with pytest.raises(DomainError, match="PRESENTATION_INVALID"):
            await WorkspacePresentationReads(files, files.read).read(
                {"path": str(path), "view": "document"},
                {"taskId": "task", "workspace": {"directory": str(tmp_path)}},
            )
        assert path.read_bytes() == body
    finally:
        await files.close()


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

    from roami_agent.documents.presentation import NS, text_color

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
