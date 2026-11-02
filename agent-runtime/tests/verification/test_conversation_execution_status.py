"""Trusted transport failures must not become model-content scores."""

import copy
import json
import runpy
from pathlib import Path

import pytest

from roami_agent.improvement.evaluation import conversation_scenarios
from roami_agent.protocol.errors import ModelAdmissionRejected
from roami_agent.protocol.models import ModelEvent

REPOSITORY = Path(__file__).parents[3]
CONTROLS = json.loads((REPOSITORY / "cases/case-100-mech-cg01/input/controls.json").read_text())
CONTRACT = REPOSITORY / CONTROLS["contract"]


class Transport:
    model = "local-execution-control"

    def __init__(self, responses):
        self.responses = iter(responses)

    async def stream(self, messages, tools):
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        yield ModelEvent("text", response)
        yield ModelEvent(
            "usage",
            {"inputTokens": 1, "outputTokens": 1, "requestAttempts": 1, "retryUsageKnown": True},
        )


def scenario():
    return copy.deepcopy(json.loads(CONTRACT.read_text())["scenarios"][0])


def summary(result):
    module = runpy.run_path(str(REPOSITORY / "scripts/dev/run-conversation-scenarios.py"))
    return module["execution_summary"]({"results": [result], "failure": None})


@pytest.mark.parametrize("code", CONTROLS["admission_errors"])
async def test_admission_rejection_is_unscored_and_reaches_top_summary(tmp_path, monkeypatch, code):
    def forbidden(*args):
        pytest.fail("An unexecuted turn must not enter the semantic oracle")

    monkeypatch.setattr(conversation_scenarios, "grade_checkpoint", forbidden)
    result = await conversation_scenarios.run_conversation(
        scenario(), tmp_path / "blocked", provider=Transport([ModelAdmissionRejected(code)])
    )
    assert result["state"] == "blocked" and result["failure"] == code
    assert not result["passed"] and not result["live_model_semantics_tested"]
    assert result["checkpoints"] == [
        {
            "turn": 1,
            "passed": False,
            "failures": [],
            "semantic_checked": False,
            "state": "blocked",
            "failure": code,
        }
    ]
    assert result["metrics"]["request_attempts"] == result["metrics"]["observed_tokens"] == 0
    assert result["metrics"]["token_coverage"] == "complete"
    assert summary(result) == {
        "failure": code,
        "blocked_scenarios": 1,
        "failed_scenarios": 0,
        "semantic_checked_user_turns": 0,
        "live_model_semantics_tested": False,
    }


async def test_second_turn_block_keeps_first_semantic_result(tmp_path):
    source = scenario()
    answer = json.dumps(source["turns"][0]["expect"]["reply_json"])
    result = await conversation_scenarios.run_conversation(
        source,
        tmp_path / "partial",
        provider=Transport([answer, ModelAdmissionRejected("MODEL_PROXY_USAGE_UNKNOWN")]),
    )
    assert [c["state"] for c in result["checkpoints"]] == ["passed", "blocked"]
    assert result["metrics"]["request_attempts"] == 1
    assert summary(result)["semantic_checked_user_turns"] == 1
    assert result["live_model_semantics_tested"] and not result["passed"]


@pytest.mark.parametrize(
    "answer,failures",
    [
        ("invalid JSON", ["CHAT_JSON_REQUIRED"]),
        ('{"主题":null}', ["CHAT_CONSTRAINTS_MISMATCH"]),
        ("MODEL_PROXY_USAGE_UNKNOWN", ["CHAT_JSON_REQUIRED"]),
    ],
)
async def test_completed_wrong_content_remains_a_semantic_failure(tmp_path, answer, failures):
    result = await conversation_scenarios.run_conversation(
        scenario(), tmp_path / "wrong", provider=Transport([answer])
    )
    assert result["state"] == "failed" and result["failure"] is None
    assert result["checkpoints"][0]["failures"] == failures
    assert result["checkpoints"][0]["semantic_checked"]
    assert result["live_model_semantics_tested"]
    assert summary(result)["failed_scenarios"] == 1


async def test_transport_failure_with_unknown_usage_stops_without_semantic_score(tmp_path):
    result = await conversation_scenarios.run_conversation(
        scenario(), tmp_path / "transport", provider=Transport([RuntimeError("network failed")])
    )
    assert result["failure"] == "RuntimeError"
    assert result["state"] == "failed"
    assert result["checkpoints"][0]["failures"] == []
    assert not result["checkpoints"][0]["semantic_checked"]
    assert result["metrics"]["token_coverage"] != "complete"
    assert not result["live_model_semantics_tested"]


def test_driver_failure_takes_priority_over_episode_failure():
    module = runpy.run_path(str(REPOSITORY / "scripts/dev/run-conversation-scenarios.py"))
    assert (
        module["execution_summary"]({"results": [], "failure": "EPISODE_RECEIPT_UNAVAILABLE"})[
            "failure"
        ]
        == "EPISODE_RECEIPT_UNAVAILABLE"
    )
