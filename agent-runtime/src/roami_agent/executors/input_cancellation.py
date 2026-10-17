"""Nested cancellation keeps possible input alive until the adapter proves it stopped."""

import asyncio
import functools
from contextvars import ContextVar

from roami_agent.protocol.errors import ToolCancellation

_pending_input = ContextVar("roami_pending_input", default=False)


def input_started():
    _pending_input.set(True)


def input_stopped():
    _pending_input.set(False)


def passive_cancel_boundary(function):
    @functools.wraps(function)
    async def run(*args, **kwargs):
        try:
            return await function(*args, **kwargs)
        except ToolCancellation:
            raise
        except asyncio.CancelledError:
            raise ToolCancellation(input_stopped=not _pending_input.get()) from None

    return run
