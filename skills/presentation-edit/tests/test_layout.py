"""Drawing order, scaled group coordinates and visible placement are distinct facts."""

import io
import zipfile
from xml.etree import ElementTree as E

import pytest
from pptx_package import NS, presentation_metadata
from presentation_fixture import presentation_bytes


def layout_presentation(*, group_rotation=0, group_flip=None, missing_size=False):
    with zipfile.ZipFile(io.BytesIO(presentation_bytes())) as source:
        parts = {name: source.read(name) for name in source.namelist()}
    tree = E.fromstring(parts["ppt/slides/slide1.xml"])
    shapes = tree.find("p:cSld/p:spTree", NS)
    # First drawn text is a lower caption; the last drawn text is the top heading.
    body = shapes.find("p:grpSp/p:sp", NS)
    heading = shapes.findall("p:sp", NS)[-1]
    for shape, x, y, width, height in [(body, 0, 0, 10, 10), (heading, 20, 25, 30, 10)]:
        properties = E.SubElement(shape, "{" + NS["p"] + "}spPr")
        transform = E.SubElement(properties, "{" + NS["a"] + "}xfrm")
        E.SubElement(transform, "{" + NS["a"] + "}off", x=str(x), y=str(y))
        if not (missing_size and shape is heading):
            E.SubElement(
                transform, "{" + NS["a"] + "}ext", cx=str(width), cy=str(height)
            )
    group = shapes.find("p:grpSp/p:grpSpPr", NS)
    transform = E.SubElement(group, "{" + NS["a"] + "}xfrm", rot=str(group_rotation))
    if group_flip:
        transform.set(group_flip, "1")
    for tag, attributes in [
        ("off", {"x": "100", "y": "200"}),
        ("ext", {"cx": "200", "cy": "100"}),
        ("chOff", {"x": "0", "y": "0"}),
        ("chExt", {"cx": "100", "cy": "50"}),
    ]:
        E.SubElement(transform, "{" + NS["a"] + "}" + tag, attributes)
    parts["ppt/slides/slide1.xml"] = E.tostring(tree)
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as output:
        for name, body in parts.items():
            output.writestr(name, body)
    return result.getvalue()


def test_spatial_order_is_not_the_drawing_traversal():
    result = presentation_metadata(layout_presentation())
    slide = result["slides"][0]
    assert [item["text"] for item in slide["textObjects"]] == ["正文", "Heading"]
    assert [item["drawingOrdinal"] for item in slide["textObjects"]] == [1, 2]
    assert [item["topToBottomRank"] for item in slide["textObjects"]] == [2, 1]
    assert all("ordinal" not in item for item in slide["textObjects"])
    assert slide["topToBottomPaths"] == [[2], [1, 0]]
    assert slide["textObjects"][0]["slideBounds"] == {
        "x": 100,
        "y": 200,
        "width": 20,
        "height": 20,
    }
    assert slide["textObjects"][1]["slideBounds"] == {
        "x": 20,
        "y": 25,
        "width": 30,
        "height": 10,
    }
    assert result["rendered"] is False


@pytest.mark.parametrize(
    "rotation,flip,expected",
    [
        (90 * 60000, None, {"x": 230, "y": 150, "width": 20, "height": 20}),
        (0, "flipH", {"x": 280, "y": 200, "width": 20, "height": 20}),
        (0, "flipV", {"x": 100, "y": 280, "width": 20, "height": 20}),
    ],
)
def test_group_transform_matches_hand_computed_bounds(rotation, flip, expected):
    item = presentation_metadata(
        layout_presentation(group_rotation=rotation, group_flip=flip)
    )["slides"][0]["textObjects"][0]
    assert item["slideBounds"] == expected


def test_inherited_or_missing_geometry_does_not_invent_a_global_first_object():
    slide = presentation_metadata(layout_presentation(missing_size=True))["slides"][0]
    assert slide["textObjects"][0]["slideBounds"] is not None
    assert slide["textObjects"][1]["slideBounds"] is None
    assert slide["topToBottomPaths"] is None


def repack(body, edit):
    with zipfile.ZipFile(io.BytesIO(body)) as source:
        parts = {name: source.read(name) for name in source.namelist()}
    tree = E.fromstring(parts["ppt/slides/slide1.xml"])
    edit(tree)
    parts["ppt/slides/slide1.xml"] = E.tostring(tree)
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as output:
        for name, value in parts.items():
            output.writestr(name, value)
    return result.getvalue()


def test_nested_groups_with_child_offsets_compose_in_slide_coordinates():
    def nest(tree):
        group = tree.find("p:cSld/p:spTree/p:grpSp", NS)
        outer = group.find("p:grpSpPr/a:xfrm/a:chOff", NS)
        outer.set("x", "10")
        outer.set("y", "20")
        body = group.find("p:sp", NS)
        group.remove(body)
        nested = E.SubElement(group, "{" + NS["p"] + "}grpSp")
        properties = E.SubElement(nested, "{" + NS["p"] + "}grpSpPr")
        transform = E.SubElement(properties, "{" + NS["a"] + "}xfrm")
        for tag, values in [
            ("off", {"x": "20", "y": "30"}),
            ("ext", {"cx": "40", "cy": "20"}),
            ("chOff", {"x": "-10", "y": "-20"}),
            ("chExt", {"cx": "20", "cy": "10"}),
        ]:
            E.SubElement(transform, "{" + NS["a"] + "}" + tag, values)
        nested.append(body)

    item = presentation_metadata(repack(layout_presentation(), nest))["slides"][0][
        "textObjects"
    ][0]
    # Each group doubles size; translations give x=160+4u, y=300+4v.
    assert item["shapePath"] == [1, 0, 0]
    assert item["slideBounds"] == {"x": 160, "y": 300, "width": 40, "height": 40}


def test_shape_rotation_preserves_its_center_and_reports_axis_aligned_bounds():
    def rotate(tree):
        shape = tree.findall("p:cSld/p:spTree/p:sp", NS)[-1]
        shape.find("p:spPr/a:xfrm", NS).set("rot", str(90 * 60000))

    item = presentation_metadata(repack(layout_presentation(), rotate))["slides"][0][
        "textObjects"
    ][1]
    assert item["slideBounds"] == {"x": 30, "y": 15, "width": 10, "height": 30}


@pytest.mark.parametrize("kind", ["missing", "zero_child_extent"])
def test_unresolved_group_layout_does_not_become_local_coordinate_order(kind):
    def invalidate(tree):
        group = tree.find("p:cSld/p:spTree/p:grpSp/p:grpSpPr", NS)
        if kind == "missing":
            group.remove(group.find("a:xfrm", NS))
        else:
            group.find("a:xfrm/a:chExt", NS).set("cx", "0")

    slide = presentation_metadata(repack(layout_presentation(), invalidate))["slides"][
        0
    ]
    assert slide["topToBottomPaths"] is None
    assert slide["textObjects"][0]["slideBounds"] is None
    assert slide["textObjects"][0]["localPosition"] == {"x": 0, "y": 0}


def test_external_inspection_cli_exposes_layout_without_rewriting_source(
    tmp_path, capsys
):
    import hashlib
    import json

    from presentation import main

    body = layout_presentation()
    path = tmp_path / "deck.pptx"
    path.write_bytes(body)
    assert main(["inspect", "--workspace", str(tmp_path), "--path", path.name]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["ok"] is True
    assert document["sha256"] == hashlib.sha256(body).hexdigest()
    assert document["objectOrder"] == "drawing_traversal"
    assert document["coordinateUnit"] == "EMU"
    assert document["slides"][0]["topToBottomPaths"] == [[2], [1, 0]]
    assert path.read_bytes() == body
