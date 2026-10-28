"""Host-authoritative Codex receipts, quota recovery, and unknown-operation isolation."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from test_improvement_codex_gateway import Provider, plan, settings
from test_improvement_codex_roles import codex_events
from test_improvement_pipeline import setup_run

from roami_agent.improvement.integrations.codex_gateway import CodexTextGateway
from roami_agent.improvement.persistence.run_costs import RunCosts
from roami_agent.improvement.workflows.codex_roles import codex_json
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent


async def invoke_local_gateway(argv, *, env, **kwargs):
    base = next(
        json.loads(a.split("=", 1)[1])
        for a in argv
        if a.startswith("model_providers.roami_rsi_go.base_url=")
    )
    async with httpx.AsyncClient(trust_env=False) as client:
        response = await client.post(
            base + "/responses",
            headers={"Authorization": "Bearer " + env["ROAMI_RSI_CODEX_GATEWAY_KEY"]},
            json={"model": "gpt-6.1-sol", "stream": True, "input": "fixture"},
        )
    good = "response.completed" in response.text
    return {
        "exitCode": 0 if good else 1,
        "stdout": codex_events(tokens=20) if good else "",
        "stderr": "",
    }


def bind(monkeypatch, tmp_path):
    service, run = setup_run(tmp_path)
    service.ledger.shared_daily_limit = True
    monkeypatch.setattr(
        "roami_agent.improvement.workflows.codex_roles.codex_configuration",
        lambda **kwargs: ({"model": "gpt-6.1-sol"}, {}),
    )
    return service, RunCosts(service.runs, "local", run)


async def test_completed_receipt_uses_host_usage_and_reuses_without_catalog_or_spend(
    tmp_path, monkeypatch
):
    _service, workflow = bind(monkeypatch, tmp_path)
    calls, resolved = [], []

    async def resolve(*args, **kwargs):
        resolved.append(True)
        return plan(calls)

    monkeypatch.setattr("roami_agent.improvement.workflows.codex_roles.gateway_plan", resolve)
    action = {"id": "host-usage", "kind": "review", "owner": "local"}
    args = (workflow, action, {"model_tokens": 1, "model_seconds": 30}, "report", [])
    first = await codex_json(*args, settings=settings(), runner=invoke_local_gateway)
    assert first["metrics"]["tokens"] == 130 and first["cli_metrics"]["tokens"] == 40
    assert first["metrics"]["usage_scope"] == "host_go_gateway"
    assert first["metrics"]["model_calls"] == 1 and first["metrics"]["cached_input_tokens"] == 10
    assert first["gateway"]["gateway_model"] == "rr/gpt-6.1-sol"
    second = await codex_json(*args, settings=settings(), runner=invoke_local_gateway)
    assert first == second and len(calls) == len(resolved) == 1
    receipt = Path(first["log"]).with_name("gateway-usage.json")
    assert receipt.stat().st_mode & 0o077 == 0
    assert "messages" not in json.loads(receipt.read_text())["requests"][0]
    assert json.loads(receipt.read_text())["requests"][0]["role"] == "rsi_codex_review"


async def test_quota_rejection_is_archived_without_replaying_paid_work(tmp_path, monkeypatch):
    service, workflow = bind(monkeypatch, tmp_path)
    calls = []

    class Rejected:
        model = "rr/gpt-6.1-sol"

        async def stream(self, messages, tools):
            calls.append("rejected")
            raise DomainError("MODEL_HTTP_402")
            yield

    async def resolve(*args, **kwargs):
        value = plan(calls)
        value.factory = lambda *_: Rejected() if not calls else Provider(calls)
        return value

    monkeypatch.setattr("roami_agent.improvement.workflows.codex_roles.gateway_plan", resolve)
    action = {"id": "quota", "kind": "review", "owner": "local"}
    args = (workflow, action, {"model_tokens": 1, "model_seconds": 30}, "report", [])
    with pytest.raises(DomainError, match="MODEL_HTTP_402"):
        await codex_json(*args, settings=settings(), runner=invoke_local_gateway)
    rejected = workflow.operation_result("local", "quota:report")["value"]
    assert rejected["admission_rejected"] is True and rejected["metrics"]["tokens"] == 0
    completed = await codex_json(*args, settings=settings(), runner=invoke_local_gateway)
    assert completed["metrics"]["tokens"] == 130 and len(calls) == 2
    with service.ledger.connection() as db:
        rows = db.execute(
            "SELECT result_json FROM rsi_pipeline_costs WHERE owner='local'"
        ).fetchall()
    assert len(rows) == 2
    assert sorted(json.loads(r[0])["value"]["metrics"]["tokens"] for r in rows) == [0, 130]


async def test_unknown_provider_usage_never_replays(tmp_path, monkeypatch):
    service, workflow = bind(monkeypatch, tmp_path)
    calls = []

    async def resolve(*args, **kwargs):
        return plan(calls, unknown=True)

    monkeypatch.setattr("roami_agent.improvement.workflows.codex_roles.gateway_plan", resolve)
    action = {"id": "unknown", "kind": "review", "owner": "local"}
    args = (workflow, action, {"model_tokens": 1, "model_seconds": 30}, "report", [])
    with pytest.raises(DomainError, match="RSI_USAGE_UNKNOWN"):
        await codex_json(*args, settings=settings(), runner=invoke_local_gateway)
    with pytest.raises(DomainError, match="UNKNOWN_OPERATION"):
        await codex_json(*args, settings=settings(), runner=invoke_local_gateway)
    assert len(calls) == 1
    receipt = next(service.ledger.path.parent.glob("codex-roles/*/*/gateway-usage.json"))
    assert json.loads(receipt.read_text())["metrics"]["tokens"] is None


async def test_shared_policy_cannot_fall_back_to_personal_cli(tmp_path, monkeypatch):
    service, workflow = bind(monkeypatch, tmp_path)

    async def forbidden(*args, **kwargs):
        pytest.fail("Shared RSI must not call an unbound CLI")

    with pytest.raises(DomainError, match="SHARED_GATEWAY_REQUIRED"):
        await codex_json(
            workflow,
            {"id": "no-route", "kind": "review", "owner": "local"},
            {"model_tokens": 1, "model_seconds": 30},
            "report",
            [],
            runner=forbidden,
        )
    with service.ledger.connection() as db:
        assert db.execute("SELECT count(*) FROM rsi_pipeline_costs").fetchone()[0] == 0


async def test_private_bridge_does_not_repeat_a_model_request():
    calls, outcome = [], {}
    async with (
        CodexTextGateway(plan(calls), "review", outcome, 30) as bridge,
        httpx.AsyncClient(trust_env=False) as client,
    ):
        args = {
            "headers": {"Authorization": "Bearer " + bridge.secret},
            "json": {"model": "gpt-6.1-sol", "stream": True, "input": "fixture"},
        }
        first = await client.post(bridge.url + "/responses", **args)
        second = await client.post(bridge.url + "/responses", **args)
    assert "response.completed" in first.text and "SINGLE_TURN_REQUIRED" in second.text
    assert len(calls) == 1


async def test_unauthorized_probe_cannot_poison_a_completed_receipt():
    calls, outcome = [], {}
    async with (
        CodexTextGateway(plan(calls), "review", outcome, 30) as bridge,
        httpx.AsyncClient(trust_env=False) as client,
    ):
        body = {"model": "gpt-6.1-sol", "stream": True, "input": "fixture"}
        first = await client.post(
            bridge.url + "/responses",
            headers={"Authorization": "Bearer " + bridge.secret},
            json=body,
        )
        rejected = await client.post(bridge.url + "/responses", json=body)
    assert "response.completed" in first.text and rejected.status_code == 400
    assert "error_code" not in outcome and len(calls) == 1


async def test_text_events_are_delivered_before_generation_finishes():
    ready, release = asyncio.Event(), asyncio.Event()

    class Incremental:
        model = "rr/gpt-6.1-sol"

        async def stream(self, messages, tools):
            yield ModelEvent("text", "first")
            ready.set()
            await release.wait()
            yield ModelEvent("text", "last")
            yield ModelEvent(
                "usage",
                {
                    "inputTokens": 123,
                    "outputTokens": 7,
                    "requestAttempts": 1,
                    "retryUsageKnown": True,
                },
            )

    value = plan([])
    value.factory = lambda *_: Incremental()
    async with (
        CodexTextGateway(value, "review", {}, 30) as bridge,
        httpx.AsyncClient(trust_env=False) as client,
        client.stream(
            "POST",
            bridge.url + "/responses",
            headers={"Authorization": "Bearer " + bridge.secret},
            json={"model": "gpt-6.1-sol", "stream": True, "input": "fixture"},
        ) as response,
    ):

        async def first_delta():
            async for line in response.aiter_lines():
                if line.startswith("data: ") and '"delta": "first"' in line:
                    return line

        await asyncio.wait_for(first_delta(), 2)
        assert ready.is_set() and not release.is_set()
        release.set()
