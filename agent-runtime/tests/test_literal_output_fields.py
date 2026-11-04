import copy

import pytest

from roami_agent.replies.literal_fields import (
    literal_reading_fields,
    source_supported,
    unsupported_literal_rewrite,
)


@pytest.mark.parametrize("wrong", ["Choose Rust", None, True, 1])
def test_source_witness_rejects_unsupported_paraphrase_without_rewriting(wrong):
    source = "Return JSON: labelUse Rust."
    fields = literal_reading_fields({"label": "Use Rust"}, source)
    draft = {"label": wrong, "count": 3}
    before = copy.deepcopy(draft)
    assert unsupported_literal_rewrite(draft, fields, [source])["value"] == "Use Rust"
    assert draft == before
    assert unsupported_literal_rewrite({"label": "Use Rust"}, fields, [source]) is None


def test_unproven_or_nonliteral_reference_cannot_constrain_a_draft():
    assert literal_reading_fields({"label": "Use Rust"}, "labelUse Go") == []
    assert literal_reading_fields({"label": "Use Rust"}, "Use Rust label") == []
    assert literal_reading_fields({"label": None}, "label未定") == []
    assert literal_reading_fields(["Use Rust"], "labelUse Rust") == []


@pytest.mark.parametrize("value", ["42", "true", "null", "[1]", '{"name":1}'])
def test_textual_json_does_not_establish_the_requested_output_type(value):
    assert literal_reading_fields({"label": value}, "label" + value) == []


def test_supported_alternative_is_left_for_the_semantic_reviewer():
    source = "labelreading，另一个允许选项是science。"
    fields = literal_reading_fields({"label": "reading"}, source)
    assert unsupported_literal_rewrite({"label": "science"}, fields, [source]) is None


def test_explicit_null_does_not_inherit_an_incorrect_reference_placeholder():
    source = "label未定。只返回JSON，键label的值用null。"
    fields = literal_reading_fields({"label": "未定"}, source)
    assert unsupported_literal_rewrite({"label": None}, fields, [source]) is None


def test_translation_is_not_forced_to_copy_its_input_material():
    source = "Translate labelOriginal Value into Chinese."
    assert literal_reading_fields({"label": "标签原始值"}, source) == []


def test_old_literal_does_not_override_a_removed_or_missing_field():
    assert literal_reading_fields({"label": "Use Rust"}, "Remove label.") == []
    fields = literal_reading_fields({"label": "Use Rust"}, "labelUse Rust")
    assert unsupported_literal_rewrite({}, fields, ["labelUse Rust"]) is None


@pytest.mark.parametrize(
    "value,source,expected",
    [
        (30, "人数30", True),
        (3, "人数3000", False),
        (None, "用null", True),
        (True, "not-truely", False),
        ([], "Return []", True),
        ([], "No value supplied", False),
        (["Alice", "Bob"], "names Alice Bob", True),
    ],
)
def test_primitive_and_container_support_preserves_real_source_boundaries(value, source, expected):
    assert source_supported(value, [source]) is expected


def test_field_declaration_cannot_be_copied_as_its_own_value():
    source = "labelPlay together。"
    fields = literal_reading_fields({"label": "Play together"}, source)
    mismatch = unsupported_literal_rewrite({"label": "labelPlay together"}, fields, [source])
    assert mismatch["reason"] == "field_prefix_copied"
    assert unsupported_literal_rewrite({"label": "Play together"}, fields, [source]) is None


def test_quoted_input_material_is_not_a_field_assignment():
    source = "把完整原文“labelPlay together”存入label。"
    assert literal_reading_fields({"label": "Play together"}, source) == []
    source = "The user's assignment is labelPlay together."
    assert literal_reading_fields({"label": "Play together"}, source)


def test_explicit_prefix_inside_the_value_is_preserved():
    fields = [{"field": "label", "value": "Play together", "quote": "labelPlay together"}]
    source = 'Return {"label":"labelPlay together"} exactly.'
    assert unsupported_literal_rewrite({"label": "labelPlay together"}, fields, [source]) is None


def test_witness_cannot_bind_a_different_ascii_field_identifier():
    assert literal_reading_fields({"label": "Use Rust"}, "sublabelUse Rust") == []
    assert literal_reading_fields({"label": "Use Rust"}, "将labelUse Rust")
