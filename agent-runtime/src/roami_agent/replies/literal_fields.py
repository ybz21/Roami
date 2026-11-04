"""Check source-grounded literal readings without choosing an answer for Main."""

import json
import re


def quoted_source(source, position):
    closing, escaped = None, False
    pairs = {'"': '"', "'": "'", "“": "”", "‘": "’", "`": "`"}
    for index, char in enumerate(source[:position]):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif closing:
            if char == closing:
                closing = None
        elif char in pairs:
            if (
                char == "'"
                and index > 0
                and source[index - 1].isalnum()
                and index + 1 < len(source)
                and source[index + 1].isalnum()
            ):
                continue
            closing = pairs[char]
    return closing is not None


def field_value_pattern(field, value):
    boundary = (
        r"(?<![A-Za-z0-9_])"
        if field and field[0].isascii() and (field[0].isalnum() or field[0] == "_")
        else ""
    )
    return boundary + re.escape(field) + r'["”\x27]?\s*[:：=]?\s*["“\x27]?' + re.escape(value)


def literal_reading_fields(reading, source):
    if not isinstance(reading, dict):
        return []
    fields = []
    for field, value in reading.items():
        if not field or not isinstance(value, str) or not value:
            continue
        try:
            json.loads(value)
        except ValueError:
            pass
        else:
            # Textual JSON primitives do not establish a requested output type.
            continue
        match = next(
            (
                m
                for m in re.finditer(field_value_pattern(field, value), source)
                if not quoted_source(source, m.start())
            ),
            None,
        )
        if match is not None:
            fields.append({"field": field, "value": value, "quote": match.group()})
    return fields


def source_supported(value, sources):
    if isinstance(value, str):
        return any((value if value else '""') in source for source in sources)
    if isinstance(value, (list, dict)):
        if not value:
            return any(json.dumps(value) in source for source in sources)
        values = value.values() if isinstance(value, dict) else value
        return all(source_supported(item, sources) for item in values)
    literal = json.dumps(value, ensure_ascii=False, allow_nan=False)
    pattern = r"(?<![A-Za-z0-9_.])" + re.escape(literal) + r"(?![A-Za-z0-9_.])"
    return any(re.search(pattern, source) for source in sources)


def unsupported_literal_rewrite(draft, fields, sources):
    for item in fields:
        if item["field"] not in draft or draft[item["field"]] == item["value"]:
            continue
        value = draft[item["field"]]
        if value == item["quote"] and not any(
            re.search(field_value_pattern(item["field"], value), source) for source in sources
        ):
            return {**item, "reason": "field_prefix_copied"}
        if not source_supported(value, sources):
            return {**item, "reason": "unsupported_rewrite"}
    return None
