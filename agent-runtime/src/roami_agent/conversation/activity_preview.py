"""Bounded execution previews with the same redaction for SSE and detail reads."""

import json
import re

SENSITIVE = re.compile(
    r"^(api[-_]?key|authorization|password|passwd|secret|access[-_]?token|refresh[-_]?token|cookie|set-cookie|.*base64)$",
    re.IGNORECASE,
)


def preview(value, *, limit=16000):
    def redact(item, depth=0):
        if depth > 12:
            return "[nested content omitted]"
        if isinstance(item, dict):
            return {
                key: "[redacted]" if SENSITIVE.match(key) else redact(value, depth + 1)
                for key, value in item.items()
            }
        if isinstance(item, list):
            return [redact(value, depth + 1) for value in item]
        if isinstance(item, str):
            item = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[redacted]", item)
            item = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [redacted]", item)
            return re.sub(
                r"data:image/[^;\s]+;base64,[A-Za-z0-9+/=]+", "[image data omitted]", item
            )
        return item

    text = json.dumps(redact(value), ensure_ascii=False, indent=2)
    return {"text": text[:limit], "truncated": len(text) > limit}
