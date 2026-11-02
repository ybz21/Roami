"""An enclosing evaluator window is context, never a provider or task limit."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from roami_agent.context.execution_timing import execution_timing
from roami_agent.improvement.evaluation.execution.executors import NativeFilesExecutor
from roami_agent.improvement.evaluation.protocol_suite import protocol_suite
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings


async def test_original_evaluator_window_reaches_model_without_changing_saved_routes(tmp_path):
    messages_seen, routes = [], []
    settings = Settings()
    original = asdict(settings)

    class Model:
        model = "execution-window-fixture"

        async def stream(self, messages, tools):
            messages_seen.append(messages)
            yield ModelEvent("text", "fixture answer")
            yield ModelEvent("usage", {"prompt_tokens": 10, "completion_tokens": 2})

    def factory(effective, role):
        routes.append((role, effective.route("main" if role == "main" else "worker")))
        return Model()

    case = protocol_suite()["cases"][0]
    case["limits"]["seconds"] = 37
    original_case = json.loads(json.dumps(case))
    await NativeFilesExecutor(settings, provider_factory=factory).run(case, {}, tmp_path)
    timing_messages = [
        m["content"]
        for messages in messages_seen
        for m in messages
        if m["role"] == "system"
        and isinstance(m["content"], str)
        and m["content"].startswith("Current execution window")
    ]
    assert timing_messages, "The real outer window was hidden from the model"
    value = json.loads(timing_messages[0].split(": ", 1)[1].split(". Original task", 1)[0])
    assert 0 < value["remainingSeconds"] <= 37
    assert value["deadlineSource"] == "enclosing_execution"
    assert "elapsedSeconds" not in value and "runId" not in value
    assert all(
        route == settings.route("main" if role == "main" else "worker") for role, route in routes
    )
    assert asdict(settings) == original and case == original_case


SCENARIOS = json.loads(
    (
        Path(__file__).resolve().parents[2] / "cases/case-80-mech-ew01/input/timing-scenarios.json"
    ).read_text()
)["scenarios"]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda value: value["name"])
def test_clock_uses_existing_earliest_window_without_inventing_limits(scenario):
    turn = (
        {
            "executionRunId": "attempt",
            "executionStartedMs": 10000,
            "executionDeadlineMs": scenario["own"],
        }
        if scenario["native"]
        else {}
    )
    original = dict(turn)
    value = execution_timing(turn, scenario["observed"], enclosing_deadline_ms=scenario["outer"])
    if scenario["expected"] is None:
        assert value is None
    else:
        expected = {"observedMs": scenario["observed"], **scenario["expected"]}
        if scenario["native"]:
            expected.update(runId="attempt", startedMs=10000)
        assert value == expected
    assert turn == original
