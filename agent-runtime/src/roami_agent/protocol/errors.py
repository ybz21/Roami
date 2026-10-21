import asyncio
import re


class DomainError(Exception):
    def __init__(self, code: str, status: int = 400):
        self.code, self.status = code, status
        super().__init__(code)


class ToolPreflightError(DomainError):
    """An unavailable dependency prevents starting the tool action."""


class ToolFinalizationRequired(ToolPreflightError):
    """An unchanged blocker allows reporting existing evidence, but no further tools."""


class ToolCancellation(asyncio.CancelledError):
    def __init__(self, *, input_stopped):
        super().__init__()
        self.input_stopped = input_stopped is True


def public_error_code(value):
    return (
        value if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,100}", value) else None
    )
