"""Literal textbox edits that retain runs and reject computed-field matches."""

from pptx_package import NS, PresentationError


def paragraph_spans(paragraph):
    spans, position = [], 0
    for child in paragraph:
        if child.tag in {"{" + NS["a"] + "}" + t for t in ("pPr", "endParaRPr")}:
            continue
        texts = child.findall("a:t", NS)
        editable = (
            child.tag == "{" + NS["a"] + "}r"
            and len(texts) == 1
            and all(
                node.tag in {"{" + NS["a"] + "}" + t for t in ("rPr", "t")}
                for node in child
            )
        )
        value = "".join(node.text or "" for node in child.findall(".//a:t", NS))
        if child.tag == "{" + NS["a"] + "}br":
            value = "\n"
        elif not value and not editable:
            value = "\0"  # Unknown inline content must not join separate runs.
        spans.append(
            (position, position + len(value), texts[0] if editable else None, value)
        )
        position += len(value)
    return spans


def valid_literal(value):
    return all(
        char == "\t"
        or 0x20 <= ord(char) <= 0xD7FF
        or 0xE000 <= ord(char) <= 0xFFFD
        or 0x10000 <= ord(char) <= 0x10FFFF
        for char in value
    )


def replace_text(shape, request):
    old, new = request["old"], request["new"]
    if not old or not all(valid_literal(value) for value in (old, new)):
        raise PresentationError("PRESENTATION_TEXT_REPLACEMENT_UNSUPPORTED")
    matches = []
    for paragraph in shape.findall("p:txBody/a:p", NS):
        spans = paragraph_spans(paragraph)
        text = "".join(span[3] for span in spans)
        offset = 0
        while (start := text.find(old, offset)) >= 0:
            end = start + len(old)
            selected = [span for span in spans if span[0] < end and start < span[1]]
            if any(span[2] is None for span in selected):
                raise PresentationError("PRESENTATION_TEXT_REPLACEMENT_UNSUPPORTED")
            matches.append((start, end, selected))
            offset = end
    if len(matches) != request.get("expectedCount", 1):
        raise PresentationError("PRESENTATION_TEXT_MATCH_COUNT_MISMATCH")
    # Work backwards so the observed offsets remain valid within each run.
    for start, end, selected in reversed(matches):
        for index, (left, _, node, _) in enumerate(selected):
            value = node.text or ""
            prefix = value[: max(0, start - left)]
            suffix = value[min(len(value), end - left) :]
            node.text = prefix + (new if index == 0 else "") + suffix
            if node.text and (node.text[0].isspace() or node.text[-1].isspace()):
                node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return {"old": old, "new": new, "occurrences": len(matches)}
