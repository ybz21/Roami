"""A second cancellation cannot turn an unfinished input cleanup into a stop receipt."""

import asyncio

import pytest

from roami_agent.executors.input_cancellation import input_started, passive_cancel_boundary
from roami_agent.protocol.errors import ToolCancellation


async def test_second_cancellation_keeps_unknown_input_stop():
    cleaning = asyncio.Event()

    @passive_cancel_boundary
    async def operation():
        input_started()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaning.set()
            await asyncio.Event().wait()

    active = asyncio.create_task(operation())
    await asyncio.sleep(0)
    active.cancel()
    await asyncio.wait_for(cleaning.wait(), 1)
    active.cancel()
    with pytest.raises(ToolCancellation) as stopped:
        await active
    assert not stopped.value.input_stopped
