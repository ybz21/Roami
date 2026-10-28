"""Agent clients delegate billing and rejection to the configured Go gateway."""

import ast
import json
from pathlib import Path

import httpx
import pytest
from test_model_proxy import EVENTS, consume

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.providers.chat_completions import ChatCompletions
from roami_agent.server.configuration import Settings
from roami_agent.server.model_settings import settings_path


def test_agent_execution_has_no_local_billing_dependency():
    root = Path(__file__).parents[1] / "src/roami_agent"
    files = [root / "app.py", root / "providers/factory.py"]
    for folder in ("core", "conversation", "dispatch", "memory", "improvement/workflows"):
        files.extend((root / folder).rglob("*.py"))
    violations = []
    for path in files:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute) and node.attr == "billing":
                violations.append((str(path.relative_to(root)), node.lineno))
            if isinstance(node, ast.ImportFrom) and node.module in {
                "roami_agent.providers.model_proxy",
                "roami_agent.providers.model_billing",
            }:
                violations.append((str(path.relative_to(root)), node.lineno))
    assert not violations, violations


async def test_old_local_billing_cannot_block_main_worker_memory_or_model_settings(store):
    path = settings_path(store.data_root)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    legacy = {"dailyLimit": "obsolete", "prices": {"fixture": None}}
    path.write_text(json.dumps({"proxy": legacy}))
    path.chmod(0o600)
    await store.call(
        lambda db: db.execute(
            "INSERT INTO model_proxy_calls(id,day,timezone,role,model,started_ms,state,prices_json,cost_source) VALUES('old','2026-10-28','UTC','main','fixture',0,'unknown',?,'unknown')",
            (json.dumps({"currency": "CNY", "input": 1, "output": 4}),),
        ),
        write=True,
    )
    calls = []

    def connection(role):
        def handler(request):
            calls.append(role)
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=EVENTS
            )

        return ChatCompletions(
            "https://gateway.example/v1",
            "fixture",
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            max_retries=0,
        )

    runtime = Runtime(
        store,
        connection("main"),
        worker_model=connection("worker"),
        memory_model=connection("memory"),
        settings=Settings(endpoint="https://gateway.example/v1", model="fixture"),
    )
    try:
        for model in (runtime.model, runtime.worker_model, runtime.memory_jobs.model):
            await consume(model)
        assert calls == ["main", "worker", "memory"]
        assert not hasattr(runtime, "model_proxy")
        view = runtime.model_settings.view("local")
        assert view["gatewayManaged"] and "proxy" not in view
        assert runtime.model_settings.merge({"main": {"model": "next"}})["proxy"] == legacy
        with pytest.raises(DomainError, match="INVALID_MODEL_CONFIG"):
            runtime.model_settings.merge({"proxy": {"dailyLimit": 1}})
        assert (
            await store.call(
                lambda db: db.execute("SELECT count(*) FROM model_proxy_calls").fetchone()[0]
            )
            == 1
        )
        old = await store.call(
            lambda db: db.execute(
                "SELECT state,cost_amount FROM model_proxy_calls WHERE id='old'"
            ).fetchone()
        )
        assert old["state"] == "unknown" and old["cost_amount"] is None
    finally:
        await runtime.close()


async def test_gateway_quota_rejection_is_a_normal_provider_error_without_local_accounting(store):
    def handler(request):
        return httpx.Response(402, json={"error": {"type": "insufficient_balance"}})

    model = ChatCompletions(
        "https://gateway.example/v1",
        "fixture",
        max_retries=0,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    runtime = Runtime(store, model)
    try:
        with pytest.raises(DomainError, match="MODEL_HTTP_402"):
            await consume(runtime.model)
        assert (
            await store.call(
                lambda db: db.execute("SELECT count(*) FROM model_proxy_calls").fetchone()[0]
            )
            == 0
        )
    finally:
        await runtime.close()
