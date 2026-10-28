"""Frozen configuration defaults and identifiers for this bounded context."""

import re

STAGES = ("evaluate", "review", "issue", "repair", "verify", "publish", "observe")


DEFAULTS = {
    "revision": 0,
    "auto_publish": False,
    "daily_tokens": 1000000,
    "generation_tokens": 300000,
    "codex_tokens": 64000,
    "output_tokens": 8192,
    "main_output_tokens": None,
    "worker_output_tokens": None,
    "memory_output_tokens": 2048,
    "main_model": None,
    "main_reasoning_effort": None,
    "worker_model": None,
    "worker_reasoning_effort": None,
    "memory_model": None,
    "memory_reasoning_effort": None,
}


def code(value):
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", value)
        else "UNKNOWN"
    )
