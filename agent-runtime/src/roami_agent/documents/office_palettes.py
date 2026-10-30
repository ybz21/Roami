"""Discover the installed editor's public default color names."""

import re
from pathlib import Path
from xml.etree import ElementTree

PALETTES = (
    Path("/usr/lib/libreoffice/share/palette/standard.soc"),
    Path("/usr/share/libreoffice/share/palette/standard.soc"),
)


def installed_presentation_palette():
    for path in PALETTES:
        try:
            if path.stat().st_size > 64000:
                continue
            body = path.read_bytes()
            if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
                continue
            colors = {}
            for item in ElementTree.fromstring(body):
                values = {key.rsplit("}", 1)[-1]: value for key, value in item.attrib.items()}
                name, color = values.get("name", ""), values.get("color", "")
                if 0 < len(name) <= 128 and re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                    colors[name] = color.upper()
            if colors:
                return {
                    "editor": "LibreOffice Impress",
                    "name": "Standard",
                    "source": str(path),
                    "colors": colors,
                }
        except (OSError, ValueError, ElementTree.ParseError):
            continue
    return None
