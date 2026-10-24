import json

import httpx
import pytest
from test_improvement_control import suite_file
from test_improvement_workflow import make_suite

from roami_agent.app import Runtime
from roami_agent.improvement.experiment_preview import preview
from roami_agent.improvement.status import ImprovementStatus
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.server.http import create_app


def test_preview_checks_full_pair_budget_without_spending_or_writing(tmp_path):
    service = ImprovementStatus(tmp_path)
    control = service.control
    control.register_machine("local", {"id": "a", "label": "A", "mode": "container"})
    control.register_suite("local", suite_file(tmp_path))
    control.save(
        "local",
        {**control.preferences("local"), "suite_id": "data", "machine_ids": ["a"]},
    )
    with service.ledger.connection() as db:
        before = list(db.iterdump())
    result = preview(service, "local", Settings())
    assert result["cases"] == 60 and result["episodes"] == 120
    assert result["reservation_tokens"] == 20000
    assert {"RSI_FORMAL_SUITE_INCOMPLETE", "RSI_BUDGET_REQUIRED"} <= set(result["blockers"])
    assert result["next_run"] is None and result["runtime_preflight_required"]
    with service.ledger.connection() as db:
        assert list(db.iterdump()) == before
    assert "RSI_SUITE_NOT_FOUND" in preview(service, "other", Settings())["blockers"]


def test_missing_artifact_calibration_is_explicit_and_not_a_zero_cost_estimate(tmp_path):
    service = ImprovementStatus(tmp_path)
    path = tmp_path / "formal.json"
    path.write_text(json.dumps(make_suite()))
    service.control.register_suite("local", path)
    service.control.save("local", {**service.control.preferences("local"), "suite_id": "daily"})
    result = preview(service, "local", Settings())
    assert result["artifact_cases"] > 0
    assert "RSI_ARTIFACT_REVIEW_REQUIRED" in result["blockers"]
    assert result["reservation_tokens"] is None


def test_visual_configuration_preserves_trusted_targets_and_rejects_stale_writes(tmp_path):
    service = ImprovementStatus(tmp_path)
    workflow = service.research
    initial = workflow.configure(
        "local", {**workflow.settings("local"), "repo": str(tmp_path), "base_commit": "a" * 40}
    )
    fields = {
        k: initial[k]
        for k in (
            "revision",
            "enabled",
            "model_tokens",
            "model_seconds",
            "max_attempts",
            "observation_days",
        )
    }
    saved = workflow.configure_experiment("local", {**fields, "max_attempts": 3})
    assert saved["repo"] == str(tmp_path) and saved["base_commit"] == "a" * 40
    assert saved["repair_executor"] == "codex" and saved["max_attempts"] == 3
    with pytest.raises(DomainError, match="SETTINGS_CONFLICT"):
        workflow.configure_experiment("local", fields)
    with pytest.raises(DomainError):
        workflow.configure_experiment("local", {**fields, "repo": "/untrusted"})
    assert workflow.settings("other")["revision"] == 0


@pytest.mark.parametrize("development", [False, True])
async def test_preview_and_visual_settings_are_development_only(store, development):
    runtime = Runtime(store, object(), development_rsi=development)
    app = create_app(runtime, manage_lifecycle=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        headers = {"X-Roami-Owner": "local"}
        result = await client.post("/v1/improvement/preview", headers=headers)
        assert result.status_code == (200 if development else 404)
        fields = {
            "revision": 0,
            "enabled": False,
            "model_tokens": 32000,
            "model_seconds": 90,
            "max_attempts": 1,
            "observation_days": 3,
        }
        result = await client.put("/v1/improvement/research", headers=headers, json=fields)
        assert result.status_code == (200 if development else 404)
        if development:
            assert result.json()["data"]["model_tokens"] == 32000
