"""Malformed paid JSON blocks its action without killing the research queue."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_improvement_codex_roles import codex_events
from test_improvement_workflow import setup

from roami_agent.improvement.domain.codex_result import completed_result
from roami_agent.improvement.workflows.behavior_observer import observe_cycle, prefetch_reviews
from roami_agent.improvement.workflows.research_worker import ResearchWorker
from roami_agent.improvement.workflows.review_report import build_review_report, compose_issue
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings

FIXTURE = json.loads((Path(__file__).parent / "fixtures/model-result-shapes.json").read_text())
VALUES = FIXTURE["invalid_objects"]


def paid_json(monkeypatch, value):
    async def respond(*args, **kwargs):
        return {"text": json.dumps(value)}

    monkeypatch.setattr("roami_agent.improvement.workflows.behavior_observer.model_json", respond)


@pytest.mark.parametrize("value", VALUES)
async def test_period_report_rejects_nonobject_paid_response(monkeypatch, value):
    paid_json(monkeypatch, value)
    with pytest.raises(DomainError, match="RSI_INVALID_REVIEW_REPORT"):
        await build_review_report(
            object(), {}, Settings(), {}, {"id": "fixture", "day": "fixture", "trials": []}, []
        )


@pytest.mark.parametrize("value", VALUES)
async def test_batch_review_rejects_nonobject_paid_response(monkeypatch, value):
    paid_json(monkeypatch, value)
    with pytest.raises(DomainError, match="RSI_INVALID_OBSERVATION"):
        await prefetch_reviews(
            object(), {}, Settings(), {}, {"baseline:C": {"protected": False}}, {}
        )


@pytest.mark.parametrize("value", VALUES)
async def test_issue_plan_rejects_nonobject_paid_response(monkeypatch, tmp_path, value):
    paid_json(monkeypatch, value)
    monkeypatch.setattr(
        "roami_agent.improvement.integrations.github_client.publication_profile",
        lambda *args: {"repository": "fixture/repository"},
    )
    workflow = SimpleNamespace(
        ledger=SimpleNamespace(path=tmp_path / "ledger.sqlite3"),
        report=lambda *args: {"day": "fixture", "points": []},
        report_ready=lambda *args: True,
    )
    with pytest.raises(DomainError, match="RSI_INVALID_ISSUE_PLAN"):
        await compose_issue(
            workflow, {"owner": "fixture", "payload": {"cycle_id": "fixture"}}, Settings(), {}
        )


class ScriptedModel:
    model = "public-protocol-fixture"

    def __init__(self, value):
        self.value, self.calls = value, 0

    async def stream(self, messages, tools):
        self.calls += 1
        yield ModelEvent("text", json.dumps(self.value))
        yield ModelEvent("usage", dict(FIXTURE["usage"]))


@pytest.mark.parametrize("value", FIXTURE["invalid_read_requests"])
async def test_observer_rejects_nonobject_evidence_request(tmp_path, value):
    workflow, config, _, _, cycle = await setup(tmp_path)
    workflow.discover()
    action = workflow.claim()
    model = ScriptedModel({"reviewed": True, "reads": [value], "findings": []})
    with pytest.raises(DomainError, match="RSI_INVALID_EVIDENCE_REFERENCE"):
        await observe_cycle(workflow, action, Settings(), config, provider_factory=lambda _: model)
    assert model.calls == 1
    assert workflow.review_saved("owner", cycle["cycle_id"]) == {}


@pytest.mark.parametrize("value", VALUES)
def test_cli_nonobject_event_has_domain_failure(value):
    raw = codex_events() + "\n" + json.dumps(value)
    with pytest.raises(DomainError, match="RSI_INVALID_MODEL_OUTPUT"):
        completed_result(raw)


@pytest.mark.parametrize("value", VALUES)
def test_cli_nonobject_usage_has_domain_failure(value):
    events = [json.loads(line) for line in codex_events().splitlines()]
    events[-1]["usage"] = value
    with pytest.raises(DomainError, match="RSI_USAGE_UNKNOWN"):
        completed_result("\n".join(json.dumps(e) for e in events))


@pytest.mark.parametrize("value", [v for v in VALUES if not isinstance(v, str)])
def test_cli_nonstring_event_type_has_domain_failure(value):
    raw = codex_events() + "\n" + json.dumps({"type": value})
    with pytest.raises(DomainError, match="RSI_INVALID_MODEL_OUTPUT"):
        completed_result(raw)


async def test_research_queue_survives_bad_paid_report_and_preserves_receipt(tmp_path):
    workflow, _, clock, _, cycle = await setup(tmp_path)
    workflow.discover()
    snapshot = workflow.snapshot("owner")
    review_id = next(a["id"] for a in snapshot["actions"] if a["kind"] == "review")
    clock.value += 1
    with workflow.ledger.connection() as db:
        next_id = workflow._enqueue(
            db, "owner", "issue", "public-fixture-next-action", {"cycle_id": cycle["cycle_id"]}
        )
    model = ScriptedModel([])
    reached_next = asyncio.Event()

    async def bad_report(action, config):
        return await build_review_report(
            workflow,
            action,
            Settings(),
            config,
            workflow.ledger.get("owner", cycle["cycle_id"]),
            [],
            provider_factory=lambda _: model,
        )

    async def next_action(action, config):
        reached_next.set()
        raise DomainError("RSI_FIXTURE_CONTROL_STOP")

    worker = ResearchWorker(
        SimpleNamespace(settings=SimpleNamespace(current=Settings())),
        SimpleNamespace(ledger=workflow.ledger, research=workflow),
        handlers={"review": bad_report, "issue": next_action},
    )
    await worker.start()
    try:
        await asyncio.wait_for(reached_next.wait(), 3)
        async with asyncio.timeout(3):
            while True:
                actions = {a["id"]: a for a in workflow.snapshot("owner")["actions"]}
                if actions[next_id]["state"] == "blocked":
                    break
                await asyncio.sleep(0.01)
        assert actions[review_id]["state"] == "blocked"
        assert actions[review_id]["error_code"] == "RSI_INVALID_REVIEW_REPORT"
        assert actions[next_id]["error_code"] == "RSI_FIXTURE_CONTROL_STOP"
        assert worker.task is not None and not worker.task.done()
    finally:
        await worker.close()
    operation = review_id + ":period-report"
    saved = workflow.operation_result("owner", operation)
    assert saved["value"]["text"] == "[]" and saved["value"]["metrics"]["tokens"] == 120
    assert model.calls == 1
    workflow.resume("owner", review_id)
    await worker.execute(workflow.claim())
    assert model.calls == 1 and workflow.operation_result("owner", operation) == saved
    actions = {a["id"]: a for a in workflow.snapshot("owner")["actions"]}
    assert actions[review_id]["state"] == "blocked"
    assert actions[review_id]["error_code"] == "RSI_INVALID_REVIEW_REPORT"
