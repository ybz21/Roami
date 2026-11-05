"""Routing acceptance verifies the source-bound choice rather than a reason label."""

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def selection_matches():
    path = Path(__file__).resolve().parents[3] / "scripts/dev/agent-acceptance/routing_exam.py"
    spec = importlib.util.spec_from_file_location("routing_exam", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.executor_selection_matches


@pytest.mark.parametrize("legacy", [False, True])
def test_actual_executor_override_survives_reason_label_changes(selection_matches, legacy):
    plan = {
        "executor": "codex",
        "routingDecision": {
            "executor": "codex",
            "sourceMessageId": "current-user-message",
            "reasonCode": "explicit_executor" if legacy else "tool_executor",
        },
    }
    calls = [
        {
            "tool_name": "delegate",
            "state": "succeeded",
            "arguments_json": json.dumps(
                {"routing": {"explicitExecutor": "codex"}} if legacy else {"executor": "codex"}
            ),
        }
    ]
    assert selection_matches(plan, "current-user-message", calls, "codex")
    assert not selection_matches(plan, "another-message", calls, "codex")
    assert not selection_matches(plan, "current-user-message", calls, "claude")
    calls[0]["state"] = "failed"
    assert not selection_matches(plan, "current-user-message", calls, "codex")


def test_default_executor_and_unbound_claims_cannot_pass_explicit_choice(selection_matches):
    plan = {"executor": "codex", "routingDecision": {"executor": "codex"}}
    calls = [{"tool_name": "delegate", "state": "succeeded", "arguments_json": "{}"}]
    assert not selection_matches(plan, "current-user-message", calls, "codex")
    plan["routingDecision"]["sourceMessageId"] = "current-user-message"
    assert not selection_matches(plan, "current-user-message", calls, "codex")
    calls[0]["arguments_json"] = '{"executor":"claude"}'
    assert not selection_matches(plan, "current-user-message", calls, "codex")
