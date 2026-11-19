"""Persistent continuation changes current work without rewriting initial task scope."""

import pytest

from roami_agent.storage.task_instruction import current_instruction


@pytest.mark.parametrize("kind", ["new_session", "project", "new_project"])
def test_unbound_targets_do_not_receive_persistent_continuation(kind):
    assert (
        current_instruction(
            {"target": {"kind": kind}, "goal": "initial", "continuation": {"text": "old session"}}
        )
        == "initial"
    )


def test_original_session_runs_latest_assignment_without_erasing_history():
    intent = {
        "target": {"kind": "session"},
        "goal": "draft only\nMain assignment: publish reviewed item",
        "continuation": {"text": "reconcile original submit; never resend"},
    }
    assert current_instruction(intent) == "reconcile original submit; never resend"
    assert intent["goal"].startswith("draft only")


@pytest.mark.parametrize("continuation", [{}, {"text": ""}, {"text": None}])
def test_session_without_new_instruction_retains_original_scope(continuation):
    assert (
        current_instruction(
            {"target": {"kind": "session"}, "goal": "original scope", "continuation": continuation}
        )
        == "original scope"
    )
