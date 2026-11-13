"""Executor wire identifiers; registration and availability belong to the Go catalog."""

import re

EXECUTOR_PATTERN = r"^[a-z][a-z0-9-]{0,63}$"


def is_executor(value):
    return (
        isinstance(value, str)
        and bool(re.fullmatch(EXECUTOR_PATTERN, value))
        and value not in {"auto", "unknown", "none", "shell", "terminal", "roami"}
    )


def executor_schema():
    return {
        "type": "string",
        "pattern": EXECUTOR_PATTERN,
        "description": "native or a kind returned by agent execution catalog",
    }
