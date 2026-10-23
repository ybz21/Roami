"""Installed runtimes ignore persisted RSI settings and expose no RSI actions."""

import asyncio
import json

import httpx
import pytest

from roami_agent.app import Runtime
from roami_agent.improvement.control import ImprovementControl
from roami_agent.improvement.ledger import Ledger
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.http import create_app


class Model:
    model = "fixture"

    async def stream(self, messages, tools):
        yield ModelEvent("text", "Ordinary chat still works.")


@pytest.mark.parametrize("old_settings", [False, True])
async def test_release_has_no_rsi_routes_workers_policy_binding_or_ledger_writes(
    store, monkeypatch, old_settings
):
    root = store.data_root / "agents" / "improvement"
    ledger = Ledger(root / "ledger.sqlite3")
    if old_settings:
        control = ImprovementControl(ledger)
        preferences = control.preferences("local")
        with ledger.connection() as db:
            db.execute(
                "INSERT INTO rsi_preferences VALUES(?,?,?,?)",
                ("local", 1, json.dumps({**preferences, "enabled": True}), 0),
            )
    before = {p.name: p.read_bytes() for p in root.iterdir()} if root.exists() else {}

    def forbidden(*args, **kwargs):
        raise AssertionError("Release runtime must not construct RSI services or workers")

    monkeypatch.setattr("roami_agent.app.ImprovementStatus", forbidden)
    monkeypatch.setattr("roami_agent.improvement.worker.EvaluationWorker", forbidden)
    monkeypatch.setattr("roami_agent.improvement.research_worker.ResearchWorker", forbidden)
    runtime = Runtime(store, Model())
    assert runtime.improvement is None
    store.managed = True
    await runtime.start()
    try:
        app = create_app(runtime, manage_lifecycle=False)
        assert not any(r.path.startswith("/v1/improvement") for r in app.routes)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://fixture"
        ) as client:
            headers = {"X-Roami-Owner": "local"}
            status = await client.get("/v1/status", headers=headers)
            assert status.json()["data"]["developmentRsi"] is False
            for method, path in [
                ("GET", "/v1/improvement"),
                ("POST", "/v1/improvement/requests"),
                ("PUT", "/v1/improvement/preferences"),
                ("POST", "/v1/improvement/research/fake/resume"),
                ("POST", "/v1/improvement/prepare"),
                ("POST", "/v1/improvement/releases"),
            ]:
                assert (
                    await client.request(method, path, headers=headers, json={})
                ).status_code == 404
        conversation = await runtime.conversations.create("local")
        receipt = await runtime.chat.submit("local", conversation["id"], "ordinary", "hello")
        async with asyncio.timeout(5):
            while not await store.call(
                lambda db: db.execute(
                    "SELECT 1 FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
                ).fetchone()
            ):
                await asyncio.sleep(0.01)
        view = await runtime.conversations.messages("local", conversation["id"])
        assert view["messages"][-1]["content"]["text"] == "Ordinary chat still works."
    finally:
        await runtime.close()
        store.managed = False
    after = {p.name: p.read_bytes() for p in root.iterdir()} if root.exists() else {}
    assert after == before


async def test_development_runtime_exposes_rsi_but_does_not_enable_schedule(store):
    runtime = Runtime(store, Model(), development_rsi=True)
    app = create_app(runtime, manage_lifecycle=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://fixture"
    ) as client:
        headers = {"X-Roami-Owner": "local"}
        assert (await client.get("/v1/status", headers=headers)).json()["data"][
            "developmentRsi"
        ] is True
        response = await client.get("/v1/improvement", headers=headers)
        assert response.status_code == 200
        assert response.json()["data"]["preferences"]["enabled"] is False
