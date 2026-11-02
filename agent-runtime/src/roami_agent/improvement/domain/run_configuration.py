"""Frozen configuration defaults and identifiers for this bounded context."""

import re

STAGES = ("evaluate", "review", "issue", "repair", "verify", "publish", "observe")


DEFAULTS = {"revision": 0, "auto_publish": False}

LEGACY_FIELDS = {
    "memory_reasoning_effort",
    "worker_model",
    "worker_output_tokens",
    "main_output_tokens",
    "output_tokens",
    "worker_reasoning_effort",
    "main_model",
    "generation_tokens",
    "daily_tokens",
    "main_reasoning_effort",
    "codex_tokens",
    "memory_output_tokens",
    "memory_model",
}


def code(value):
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", value)
        else "UNKNOWN"
    )
