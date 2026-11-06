"""Only one real reply tool stream may produce a provisional body."""

import json
from unittest.mock import AsyncMock

import pytest

from roami_agent.protocol.reply_stream_preview import ReplyStreamPreview
from roami_agent.protocol.reply_text_stream import MAX_PREVIEW_CHARS


@pytest.mark.parametrize(
    "other",
    [
        {"index": 1, "name": "reply", "arguments": '{"text":"other"'},
        {"index": 0, "name": "reply_bad", "arguments": '{"text":"other"'},
        {"index": 0, "name": "reply", "arguments": '{"text":"draft","json":{}'},
    ],
)
async def test_other_tool_or_conflicting_transport_retracts_the_candidate(other):
    emit = AsyncMock()
    relay = ReplyStreamPreview(True, emit, lambda: 1)
    await relay.observe({"index": 0, "name": "reply", "arguments": '{"text":"draft'})
    await relay.observe(other)
    assert emit.call_args_list[0].args == ("draft", "generating", False)
    assert emit.call_args_list[-1].args == (None, "generating", False)


async def test_complete_tool_without_wire_deltas_does_not_simulate_streaming():
    emit = AsyncMock()
    relay = ReplyStreamPreview(True, emit, lambda: 1)
    await relay.finish([{"function": {"name": "reply", "arguments": '{"text":"complete"}'}}])
    emit.assert_not_called()
    relay = ReplyStreamPreview(False, emit, lambda: 1)
    await relay.observe({"index": 0, "name": "reply", "arguments": '{"text":"worker'})
    emit.assert_not_called()


async def test_visual_preview_is_bounded_and_marks_the_clip_without_truncating_the_tool():
    emit = AsyncMock()
    text = "😀" * (MAX_PREVIEW_CHARS + 50)
    arguments = json.dumps({"text": text})
    relay = ReplyStreamPreview(True, emit, lambda: 1)
    await relay.observe({"index": 0, "name": "reply", "arguments": arguments})
    await relay.finish([{"function": {"name": "reply", "arguments": arguments}}])
    assert emit.call_args.args == (text[:MAX_PREVIEW_CHARS], "checking", True)
    assert json.loads(arguments)["text"] == text
