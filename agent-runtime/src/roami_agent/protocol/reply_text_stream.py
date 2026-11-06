"""Read only a provisional top-level reply.text from an incomplete JSON object."""

import json

MAX_PREVIEW_CHARS = 8_000
MAX_ARGUMENT_CHARS = 100_000
_DECODER = json.JSONDecoder()
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


def _string(value, start):
    result, index = [], start + 1
    while index < len(value):
        char = value[index]
        if char == '"':
            return "".join(result), index + 1, True
        if ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF:
            raise ValueError("Invalid JSON string")
        if char != "\\":
            result.append(char)
            index += 1
            continue
        index += 1
        if index == len(value):
            break
        escape = value[index]
        if escape in _ESCAPES:
            result.append(_ESCAPES[escape])
            index += 1
            continue
        if escape != "u":
            raise ValueError("Invalid JSON escape")
        if index + 5 > len(value):
            break
        digits = value[index + 1 : index + 5]
        if not all(char in _HEX_DIGITS for char in digits):
            raise ValueError("Invalid JSON Unicode escape")
        code = int(digits, 16)
        index += 5
        if 0xD800 <= code <= 0xDBFF:
            if index + 6 > len(value):
                tail = value[index:]
                if not "\\u".startswith(tail[:2]) or any(
                    char not in _HEX_DIGITS for char in tail[2:]
                ):
                    raise ValueError("Unpaired JSON surrogate")
                break
            if value[index : index + 2] != "\\u":
                raise ValueError("Unpaired JSON surrogate")
            digits = value[index + 2 : index + 6]
            if not all(char in _HEX_DIGITS for char in digits):
                raise ValueError("Invalid JSON Unicode escape")
            low = int(digits, 16)
            if not 0xDC00 <= low <= 0xDFFF:
                raise ValueError("Unpaired JSON surrogate")
            code = 0x10000 + ((code - 0xD800) << 10) + low - 0xDC00
            index += 6
        elif 0xDC00 <= code <= 0xDFFF:
            raise ValueError("Unpaired JSON surrogate")
        result.append(chr(code))
    return "".join(result), index, False


def reply_text_preview(arguments, *, limit=MAX_PREVIEW_CHARS):
    """Return a bounded draft or None; malformed/conflicting arguments retract it."""
    if not isinstance(arguments, str) or len(arguments) > MAX_ARGUMENT_CHARS:
        return None
    value = arguments.lstrip()
    if not value.startswith("{"):
        return None
    index, draft, keys, after_comma = 1, None, set(), False
    try:
        while True:
            while index < len(value) and value[index].isspace():
                index += 1
            if index == len(value):
                return draft
            if value[index] == "}":
                return draft if not after_comma and not value[index + 1 :].strip() else None
            if value[index] != '"':
                return None
            key, end, complete = _string(value, index)
            if not complete:
                return draft
            if not isinstance(key, str) or key in keys or key == "json":
                return None
            keys.add(key)
            index, after_comma = end, False
            while index < len(value) and value[index].isspace():
                index += 1
            if index == len(value):
                return draft
            if value[index] != ":":
                return None
            index += 1
            while index < len(value) and value[index].isspace():
                index += 1
            if index == len(value):
                return draft
            if key == "text":
                if value[index] != '"':
                    return None
                text, index, complete = _string(value, index)
                draft = text[:limit]
                if not complete:
                    return draft
            else:
                _, index = _DECODER.raw_decode(value, index)
            while index < len(value) and value[index].isspace():
                index += 1
            if index == len(value):
                return draft
            if value[index] == "}":
                return draft if not value[index + 1 :].strip() else None
            if value[index] != ",":
                return None
            index += 1
            after_comma = True
    except json.JSONDecodeError:
        return draft
    except (ValueError, OverflowError, RecursionError):
        return None
