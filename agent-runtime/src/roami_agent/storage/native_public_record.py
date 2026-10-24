"""Public journal payloads exclude private reasoning and known credential fields."""

import json
import re

from roami_agent.protocol.serialization import encoded

SENSITIVE = re.compile(
    r"^(api[-_]?key|authorization|password|passwd|secret|access[-_]?token|refresh[-_]?token|cookie|set-cookie)$",
    re.IGNORECASE,
)
PRIVATE = {"reasoning", "reasoning_content", "thinking"}


def public_value(value):
    if isinstance(value, dict):
        return {
            key: "[redacted]" if SENSITIVE.fullmatch(key) else public_value(item)
            for key, item in value.items()
            if key not in PRIVATE
        }
    if isinstance(value, list):
        return [public_value(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[redacted]", value)
        return re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [redacted]", value)
    return value


def public_json(value):
    return encoded(public_value(json.loads(value))) if value is not None else None
