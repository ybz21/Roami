"""Property-only PPTX edits over observed objects and explicit color specifications."""

import copy
import io
import zipfile
from xml.etree import ElementTree

from lxml import etree
from pptx_package import (
    NS,
    SHAPES,
    PresentationError,
    presentation_metadata,
    slide_parts,
)

ALIGNMENTS = {"left": "l", "center": "ctr", "right": "r", "justify": "just"}
FILLS = {"noFill", "solidFill", "gradFill", "blipFill", "pattFill", "grpFill"}


def selected_object(slide, target):
    objects = slide["textObjects"]
    if "shapePath" in target:
        selected = next(
            (item for item in objects if item["shapePath"] == target["shapePath"]), None
        )
    else:
        paths = slide["topToBottomPaths"]
        if paths is None:
            raise PresentationError("PRESENTATION_TARGET_AMBIGUOUS")
        index = target["ordinal"] - 1
        if index < 0 or index >= len(paths):
            raise PresentationError("PRESENTATION_TARGET_NOT_FOUND")
        selected = next(item for item in objects if item["shapePath"] == paths[index])
        bounds = selected["slideBounds"]
        if (
            sum(
                (item["slideBounds"]["x"], item["slideBounds"]["y"])
                == (bounds["x"], bounds["y"])
                for item in objects
            )
            != 1
        ):
            raise PresentationError("PRESENTATION_TARGET_AMBIGUOUS")
    if selected is None:
        raise PresentationError("PRESENTATION_TARGET_NOT_FOUND")
    return selected


def resolved_color(spec, palette):
    if "rgb" in spec:
        return {"rgb": "#" + spec["rgb"].lstrip("#").upper()}
    if (
        palette is None
        or spec["editor"].casefold() != palette["editor"].casefold()
        or spec["palette"].casefold() != palette["name"].casefold()
    ):
        raise PresentationError("PRESENTATION_PALETTE_UNAVAILABLE")
    matches = [
        (name, value)
        for name, value in palette["colors"].items()
        if name.casefold() == spec["name"].casefold()
    ]
    if len(matches) != 1:
        raise PresentationError("PRESENTATION_COLOR_UNKNOWN")
    name, value = matches[0]
    return {
        "rgb": value,
        "name": name,
        "editor": palette["editor"],
        "palette": palette["name"],
    }


def solid_color(properties, value):
    for child in list(properties):
        if child.tag in {"{" + NS["a"] + "}" + tag for tag in FILLS}:
            properties.remove(child)
    fill = etree.Element("{" + NS["a"] + "}solidFill")
    etree.SubElement(fill, "{" + NS["a"] + "}srgbClr", val=value)
    properties.insert(
        1 if len(properties) and properties[0].tag == "{" + NS["a"] + "}ln" else 0, fill
    )


def character_properties(parent, tag):
    existing = parent.find("a:" + tag, NS)
    if existing is not None:
        return existing
    result = etree.Element("{" + NS["a"] + "}" + tag)
    if tag == "defRPr":
        extension = parent.find("a:extLst", NS)
        parent.insert(
            list(parent).index(extension) if extension is not None else len(parent),
            result,
        )
    else:
        parent.insert(0, result)
    return result


def edit_presentation(body, operations, palette=None):
    with zipfile.ZipFile(io.BytesIO(body)) as package:
        if (
            any(info.flag_bits & 1 for info in package.infolist())
            or any(
                info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                for info in package.infolist()
            )
            or sum(info.file_size for info in package.infolist()) > 128 * 1024 * 1024
        ):
            raise ValueError("Unsupported presentation package")
        document = presentation_metadata(body)
        names = slide_parts(lambda name: ElementTree.fromstring(package.read(name)))
        if len(set(names)) != len(names):
            raise PresentationError("PRESENTATION_TARGET_AMBIGUOUS")
        roots, changes, properties = {}, [], set()
        for operation in operations:
            number = operation["slide"]
            if number < 1 or number > len(names):
                raise PresentationError("PRESENTATION_TARGET_NOT_FOUND")
            selected = selected_object(
                document["slides"][number - 1], operation["target"]
            )
            name = names[number - 1]
            if name not in roots:
                roots[name] = etree.fromstring(
                    package.read(name),
                    etree.XMLParser(resolve_entities=False, no_network=True),
                )
            shape = roots[name].find("p:cSld/p:spTree", NS)
            for index in selected["shapePath"]:
                shape = [
                    child for child in shape if child.tag.rsplit("}", 1)[-1] in SHAPES
                ][index]
            change = {"slide": number, "shapePath": selected["shapePath"]}
            color = (
                resolved_color(operation["color"], palette)
                if "color" in operation
                else None
            )
            for key in ["alignment", "color"]:
                if key not in operation:
                    continue
                identity = (name, tuple(selected["shapePath"]), key)
                if identity in properties:
                    raise PresentationError("PRESENTATION_EDIT_CONFLICT")
                properties.add(identity)
                change[key] = color if key == "color" else operation[key]
            for paragraph in shape.findall("p:txBody/a:p", NS):
                props = paragraph.find("a:pPr", NS)
                if props is None:
                    props = etree.Element("{" + NS["a"] + "}pPr")
                    paragraph.insert(0, props)
                if "alignment" in operation:
                    props.set("algn", ALIGNMENTS[operation["alignment"]])
                if color:
                    solid_color(character_properties(props, "defRPr"), color["rgb"][1:])
                    for run in paragraph:
                        if run.tag in {
                            "{" + NS["a"] + "}" + tag for tag in ["r", "fld", "br"]
                        }:
                            solid_color(
                                character_properties(run, "rPr"), color["rgb"][1:]
                            )
                    ending = paragraph.find("a:endParaRPr", NS)
                    if ending is not None:
                        solid_color(ending, color["rgb"][1:])
            changes.append(change)
        replacements = {
            name: etree.tostring(
                root, xml_declaration=True, encoding="UTF-8", standalone=True
            )
            for name, root in roots.items()
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as edited:
            edited.comment = package.comment
            for info in package.infolist():
                edited.writestr(
                    copy.copy(info),
                    replacements[info.filename]
                    if info.filename in replacements
                    else package.read(info),
                )
        return output.getvalue(), changes
