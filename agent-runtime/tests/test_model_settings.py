import asyncio
import json

import httpx
import pytest

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.server.model_settings import KEY_NAMES, load_model_settings, settings_path

FIXTURE_CREDENTIAL = "private-unit-key"
HTTP_CREDENTIAL = "fixture-sensitive-value"


class Model:
    def __init__(self, name="initial"):
        self.model, self.closed = name, False

    async def stream(self, messages, tools):
        yield ModelEvent("text", self.model)

    async def close(self):
        self.closed = True


async def test_private_save_reload_and_all_generation_routes_update(store, monkeypatch):
    for name in KEY_NAMES.values():
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("ORIGINAL_PROVIDER_KEY", "old-unit-key")
    settings = Settings(
        endpoint="http://127.0.0.1:1/v1", model="initial", key_env="ORIGINAL_PROVIDER_KEY"
    )
    runtime = Runtime(store, Model(), settings=settings)
    runtime.model_settings.factory = lambda settings, role: Model(settings.route(role).name)
    try:
        result = await runtime.model_settings.save(
            "local",
            {
                "main": {"model": "fast-fixture", "apiKey": FIXTURE_CREDENTIAL},
                "worker": {"model": "strong-fixture"},
            },
        )
        assert result["main"]["keyConfigured"] and "private-unit-key" not in json.dumps(result)
        assert "apiKey" not in json.dumps(result)
        path = settings_path(store.data_root)
        assert path.stat().st_mode & 0o777 == 0o600 and path.parent.stat().st_mode & 0o077 == 0
        assert json.loads(path.read_text())["main"]["apiKey"] == "private-unit-key"
        restored = load_model_settings(settings, store.data_root)
        assert (
            restored.model == "fast-fixture" and restored.route("worker").name == "strong-fixture"
        )
        assert "ORIGINAL_PROVIDER_KEY" in restored.provider_key_environments()
        assert set(KEY_NAMES.values()) <= restored.provider_key_environments()
        assert (
            runtime.loop.model.model
            == runtime.chat.model.model
            == runtime.context.model.model
            == "fast-fixture"
        )
        assert (
            runtime.memory_jobs.model.model
            == runtime.briefs.model.model
            == runtime.proactive.model.model
            == "strong-fixture"
        )
        first = runtime.model
        await runtime.model_settings.save("local", {"main": {"model": "another-fixture"}})
        assert first.closed
        assert runtime.settings.credentials() == "private-unit-key"
        assert not runtime.settings.updating
    finally:
        await runtime.close()


async def test_busy_configuration_never_changes_file_or_clients(store):
    runtime = Runtime(
        store, Model(), settings=Settings(endpoint="http://127.0.0.1:1/v1", model="initial")
    )
    try:
        runtime.turn_tasks["busy"] = asyncio.current_task()
        with pytest.raises(DomainError, match="MODEL_CONFIGURATION_BUSY"):
            await runtime.model_settings.save("local", {"main": {"model": "changed"}})
        assert not settings_path(store.data_root).exists()
        assert runtime.model.model == "initial" and not runtime.reconfiguring
        runtime.turn_tasks.clear()
        await runtime.briefs.lock.acquire()
        try:
            with pytest.raises(DomainError, match="MODEL_CONFIGURATION_BUSY"):
                await runtime.model_settings.save("local", {"main": {"model": "changed"}})
        finally:
            runtime.briefs.lock.release()
    finally:
        await runtime.close()


async def test_provider_discovery_uses_secret_server_side_and_blocks_redirect(store, monkeypatch):
    monkeypatch.setenv("CATALOG_KEY", "catalog-private-key")
    runtime = Runtime(
        store,
        Model(),
        settings=Settings(
            endpoint="https://catalog.example/v1", model="initial", key_env="CATALOG_KEY"
        ),
    )
    seen = []
    original = httpx.AsyncClient

    def provider(request):
        seen.append(request.headers.get("Authorization"))
        return httpx.Response(
            200, json={"data": [{"id": "model-b"}, {"id": "model-a"}, {"id": "model-a"}]}
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(provider), **kwargs),
    )
    try:
        assert await runtime.model_settings.models("local") == {
            "models": ["model-a", "model-b"],
            "truncated": False,
        }
        assert seen == ["Bearer catalog-private-key"]
        with pytest.raises(DomainError, match="MODEL_KEY_REQUIRED_FOR_ENDPOINT"):
            await runtime.model_settings.models(
                "local", patch={"main": {"baseUrl": "https://other.example/v1"}}
            )
        with pytest.raises(DomainError, match="MODEL_SETTINGS_FORBIDDEN"):
            runtime.model_settings.view("other")
    finally:
        await runtime.close()


async def test_public_views_and_validation_never_echo_keys(store, monkeypatch):
    from roami_agent.server.http import create_app

    for name in KEY_NAMES.values():
        monkeypatch.setenv(name, "")
    runtime = Runtime(
        store, Model(), settings=Settings(endpoint="http://127.0.0.1:1/v1", model="initial")
    )
    runtime.model_settings.factory = lambda settings, role: Model(settings.route(role).name)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
            base_url="http://fixture",
            headers={"X-Roami-Owner": "local"},
        ) as client:
            response = await client.put(
                "/v1/model-settings",
                json={"main": {"apiKey": HTTP_CREDENTIAL, "model": "next"}},
            )
            assert response.status_code == 200 and "fixture-sensitive-value" not in response.text
            response = await client.get("/v1/model-settings")
            assert (
                "fixture-sensitive-value" not in response.text
                and response.json()["data"]["main"]["keyConfigured"]
            )
            response = await client.put(
                "/v1/model-settings",
                json={"main": {"apiKey": HTTP_CREDENTIAL, "images": "wrong"}},
            )
            assert response.status_code == 400 and "fixture-sensitive-value" not in response.text
            assert (
                await client.post("/v1/models", json={"role": "main", "configuration": []})
            ).status_code == 400
    finally:
        await runtime.close()


async def test_failed_provider_preparation_keeps_previous_config(store, monkeypatch):
    monkeypatch.setenv(KEY_NAMES["main"], "previous-key")
    runtime = Runtime(
        store, Model(), settings=Settings(endpoint="http://127.0.0.1:1/v1", model="initial")
    )
    candidate = Model("candidate")

    def factory(settings, role):
        if role == "worker":
            raise RuntimeError("provider unavailable")
        return candidate

    runtime.model_settings.factory = factory
    try:
        with pytest.raises(RuntimeError, match="provider unavailable"):
            await runtime.model_settings.save(
                "local", {"main": {"model": "next", "apiKey": "next-key"}}
            )
        assert not settings_path(store.data_root).exists()
        assert runtime.settings.model == "initial" and runtime.model.model == "initial"
        assert candidate.closed and not runtime.reconfiguring
        import os

        assert os.environ[KEY_NAMES["main"]] == "previous-key"
    finally:
        await runtime.close()
