"""Read PowerPoint text objects in presentation and group order."""

import io
import posixpath
import zipfile
from xml.etree import ElementTree

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
SHAPES = {"sp", "grpSp", "pic", "graphicFrame", "cxnSp", "contentPart"}
ALIGNMENT = {"l": "left", "ctr": "center", "r": "right", "just": "justify"}


def text_color(properties):
    if properties is None:
        return None
    fill = properties.find("a:solidFill", NS)
    if fill is None or not len(fill):
        return None
    color = fill[0]
    kind = color.tag.rsplit("}", 1)[-1]
    result = {"kind": kind, "value": color.get("val")}
    if len(color):
        result["transforms"] = [
            {"kind": item.tag.rsplit("}", 1)[-1], **item.attrib} for item in color
        ]
    return result


def presentation_metadata(body):
    with zipfile.ZipFile(io.BytesIO(body)) as package:
        names = package.namelist()
        if len(names) > 4000 or len(set(names)) != len(names):
            raise ValueError("Invalid presentation parts")
        remaining = 16 * 1024 * 1024

        def part(name):
            nonlocal remaining
            info = package.getinfo(name)
            if info.file_size > 2 * 1024 * 1024 or info.file_size > remaining:
                raise ValueError("Oversized presentation XML")
            data = package.read(name)
            remaining -= len(data)
            if b"\0" in data or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
                raise ValueError("Unsupported presentation XML")
            return ElementTree.fromstring(data)

        presentation = part("ppt/presentation.xml")
        relations = {item.get("Id"): item for item in part("ppt/_rels/presentation.xml.rels")}
        slides = []
        for number, identifier in enumerate(presentation.findall("p:sldIdLst/p:sldId", NS), 1):
            relation = relations[identifier.get("{" + NS["r"] + "}id")]
            target = relation.get("Target", "")
            name = posixpath.normpath(
                target.lstrip("/") if target.startswith("/") else "ppt/" + target
            )
            if (
                relation.get("TargetMode") == "External"
                or not name.startswith("ppt/slides/")
                or not name.endswith(".xml")
            ):
                raise ValueError("Invalid slide relationship")
            tree = part(name).find("p:cSld/p:spTree", NS)
            if tree is None:
                raise ValueError("Missing slide objects")
            objects, empty = [], []

            def walk(parent, ancestry, objects, empty):
                if len(ancestry) > 64:
                    raise ValueError("Excessive presentation group depth")
                shapes = [child for child in parent if child.tag.rsplit("}", 1)[-1] in SHAPES]
                for index, shape in enumerate(shapes):
                    path = [*ancestry, index]
                    if shape.tag == "{" + NS["p"] + "}grpSp":
                        walk(shape, path, objects, empty)
                        continue
                    text = shape.find("p:txBody", NS)
                    if text is None:
                        continue
                    paragraphs = []
                    for paragraph in text.findall("a:p", NS):
                        value = "".join(node.text or "" for node in paragraph.findall(".//a:t", NS))
                        properties = paragraph.find("a:pPr", NS)
                        paragraphs.append(
                            {
                                "text": value,
                                "alignment": ALIGNMENT.get(
                                    properties.get("algn"), properties.get("algn")
                                )
                                if properties is not None
                                else None,
                                "runs": [
                                    {
                                        "text": "".join(
                                            node.text or "" for node in run.findall("a:t", NS)
                                        ),
                                        "color": text_color(run.find("a:rPr", NS))
                                        or text_color(paragraph.find("a:pPr/a:defRPr", NS)),
                                    }
                                    for run in paragraph.findall("a:r", NS)
                                ],
                            }
                        )
                    value = "\n".join(item["text"] for item in paragraphs)
                    if not value.strip():
                        empty.append(path)
                        continue
                    identity = shape.find("p:nvSpPr/p:cNvPr", NS)
                    transform = shape.find("p:spPr/a:xfrm/a:off", NS)
                    objects.append(
                        {
                            "ordinal": len(objects) + 1,
                            "shapePath": path,
                            "shapeId": identity.get("id") if identity is not None else None,
                            "name": identity.get("name") if identity is not None else None,
                            "text": value,
                            "paragraphs": paragraphs,
                            "localPosition": {key: int(transform.get(key)) for key in ("x", "y")}
                            if transform is not None
                            and all(key in transform.attrib for key in ("x", "y"))
                            else None,
                        }
                    )

            walk(tree, [], objects, empty)
            slides.append({"number": number, "textObjects": objects, "emptyTextFramePaths": empty})
        return {"format": "pptx", "rendered": False, "slides": slides}
