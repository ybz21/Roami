"""Standalone acceptance must resolve the same saved routes as service startup."""

import json
from dataclasses import asdict, replace

import pytest
from test_improvement_container_context import captured_request
from test_model_settings import Model

from roami_agent.app import Runtime
from roami_agent.improvement.evaluation.execution.container_agent import container_settings
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.server.model_settings import load_model_settings, settings_path


@pytest.mark.parametrize("catalog_state", ["known", "missing", "unavailable"])
async def test_standalone_capacity_matches_service_without_saving_or_changing_routes(
    store, tmp_path, monkeypatch, catalog_state
):
    from roami_agent.server.model_settings import load_runtime_model_settings

    base = Settings(
        endpoint="https://capacity.invalid/v1",
        model="base-main",
        key_env="CAPACITY_KEY",
        timeout_seconds=71,
        model_retries=1,
        model_parameters={"temperature": 0.2},
    )
    base = replace(
        base,
        worker_route=replace(
            base.route("worker"), name="base-worker", capabilities={"images": False}
        ),
    )
    monkeypatch.setenv("CAPACITY_KEY", "capacity-fixture-value")
    path = settings_path(store.data_root)
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.write_text(
        json.dumps({"main": {"model": "saved-main"}, "worker": {"model": "saved-worker"}})
    )
    path.chmod(0o600)
    original = path.read_bytes()
    seen = []

    async def catalog(endpoint, key):
        seen.append((endpoint, key))
        if catalog_state == "unavailable":
            raise DomainError("MODEL_PROVIDER_UNAVAILABLE", 502)
        return {"saved-main": 1048576, "saved-worker": 65536} if catalog_state == "known" else {}

    monkeypatch.setattr("roami_agent.server.model_settings.fetch_catalog", catalog)
    saved = load_model_settings(base, store.data_root)
    assert saved.context_window is None and saved.route("worker").context_window is None
    effective = await load_runtime_model_settings(base, store.data_root)
    runtime = Runtime(store, Model(), settings=saved)
    try:
        await runtime.model_settings.refresh_capacity()
        for role in ["main", "worker"]:
            assert effective.route(role) == runtime.settings.route(role)
            before, after = asdict(saved.route(role)), asdict(effective.route(role))
            window = after.pop("context_window")
            before.pop("context_window")
            assert before == after
            assert window == (
                {"main": 1048576, "worker": 65536}[role] if catalog_state == "known" else None
            )
        (tmp_path / "case").mkdir()
        child = container_settings(
            await captured_request(effective, tmp_path / "case", monkeypatch)
        )
        for role in ["main", "worker"]:
            assert child.route(role).context_window == effective.route(role).context_window
            assert child.threshold_for(role) == effective.threshold_for(role)
        assert path.read_bytes() == original
        assert len(seen) == 4 and set(seen) == {(base.endpoint, "capacity-fixture-value")}
    finally:
        await runtime.close()


async def test_explicit_role_capacity_never_queries_or_uses_catalog(monkeypatch, tmp_path):
    from roami_agent.server.model_settings import load_runtime_model_settings

    settings = Settings(
        endpoint="https://explicit.invalid/v1", model="chosen", context_window=24000
    )
    settings = replace(
        settings, worker_route=replace(settings.route("worker"), context_window=48000)
    )

    async def forbidden(*args):
        pytest.fail("Explicit capacity must not be overridden")

    monkeypatch.setattr("roami_agent.server.model_settings.fetch_catalog", forbidden)
    assert await load_runtime_model_settings(settings, tmp_path) == settings


async def test_capacity_discovery_cancellation_is_not_silenced(monkeypatch, tmp_path):
    import asyncio

    from roami_agent.server.model_settings import load_runtime_model_settings

    async def cancelled(*args):
        raise asyncio.CancelledError

    monkeypatch.setattr("roami_agent.server.model_settings.fetch_catalog", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await load_runtime_model_settings(
            Settings(endpoint="https://cancel.invalid/v1", model="chosen"), tmp_path
        )
