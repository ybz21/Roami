"""Preview decoding never exposes tool JSON or half a Unicode escape."""

import json

import pytest

from roami_agent.protocol.reply_text_stream import MAX_PREVIEW_CHARS, reply_text_preview


@pytest.mark.parametrize("ascii_only", [False, True])
@pytest.mark.parametrize(
    "text", ['first\nsecond "quoted" \\ path', "中文与😀下一段", "literal <reply> & JSON"]
)
@pytest.mark.parametrize("text_first", [False, True])
def test_every_wire_split_preserves_only_a_real_text_prefix(ascii_only, text, text_first):
    fields = {"mode": "brief", "requestCoverage": {"answer": ["one"]}}
    arguments = {"text": text, **fields} if text_first else {**fields, "text": text}
    wire = json.dumps(arguments, ensure_ascii=ascii_only)
    previews = [reply_text_preview(wire[:end]) for end in range(len(wire) + 1)]
    assert all(value is None or text.startswith(value) for value in previews)
    assert previews[-1] == text
    assert any(value and value != text for value in previews)
    assert all(not any(0xD800 <= ord(char) <= 0xDFFF for char in value or "") for value in previews)


@pytest.mark.parametrize(
    "wire",
    [
        '{"json":{"text":"private nested field"}}',
        '{"requestCoverage":{"text":"private nested field"}}',
        '{"text":123}',
        '{"text":"draft","json":{}}',
        '{"text":"draft","text":"replacement"}',
        '{"text":"draft"} trailing',
        '{"text":"draft",}',
        '{"text":"draft",broken key',
        '{"text":"bad\\q"}',
        '{"text":"bad\\u00ZZ"}',
        '{"text":"bad\nraw control"}',
        '[{"text":"array"}]',
        '{"text":"bad\\u+041"}',
        '{"text":"bad\\u0_41"}',
        '{"text":"bad\\ud800"}',
        '{"text":"bad\\udc00"}',
        None,
    ],
)
def test_conflicting_or_non_reply_shapes_do_not_become_prose(wire):
    assert reply_text_preview(wire) is None


def test_visual_limit_does_not_change_the_original_tool_arguments():
    text = "a" * (MAX_PREVIEW_CHARS + 1)
    wire = json.dumps({"text": text})
    assert reply_text_preview(wire) == text[:MAX_PREVIEW_CHARS]
    assert json.loads(wire)["text"] == text


def test_over_nested_metadata_retracts_without_crashing_generation():
    assert reply_text_preview('{"mode":' + "[" * 2000) is None
