import json
from dataclasses import replace

import pytest

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.server.model_verification import verification_path, verify_models


class ProbeModel:
    def __init__(self, text="OK"):
        self.text = text
        self.calls = []

    async def stream(self, messages, tools):
        self.calls.append((messages, tools))
        if self.text == "error":
            raise DomainError("MODEL_TRANSPORT_FAILED", 502)
        yield ModelEvent("text", self.text)

    async def close(self):
        pass


async def test_verification_is_private_and_bound_to_routes_and_credentials(store, monkeypatch):
    monkeypatch.setenv("ONBOARDING_TEST_KEY", "unit-test-only")
    model = ProbeModel()
    runtime = Runtime(
        store,
        model,
        settings=Settings(
            endpoint="http://localhost/v1", model="fixture", key_env="ONBOARDING_TEST_KEY"
        ),
    )
    try:
        assert not runtime.model_settings.view("local")["verified"]
        result = await verify_models(runtime.model_settings, "local")
        assert result["verified"]
        assert len(model.calls) == 1 and model.calls[0][1] == []
        path = verification_path(store.data_root)
        assert path.stat().st_mode & 0o777 == 0o600
        assert "unit-test-only" not in path.read_text() + json.dumps(result)
        marker = path.parent / "model-catalog-revision"
        marker.write_text(json.dumps({"fixture": "changed-source-with-same-alias"}))
        assert not runtime.model_settings.view("local")["verified"]
        await verify_models(runtime.model_settings, "local")
        assert runtime.model_settings.view("local")["verified"]
        marker.write_text(
            json.dumps({"fixture": "changed-source-with-same-alias", "unrelated": "new"})
        )
        assert runtime.model_settings.view("local")["verified"]
        monkeypatch.setenv("ONBOARDING_TEST_KEY", "changed-unit-test")
        assert not runtime.model_settings.view("local")["verified"]
        await verify_models(runtime.model_settings, "local")
        runtime.settings.current = replace(runtime.settings.current, model="changed-fixture")
        assert not runtime.model_settings.view("local")["verified"]
    finally:
        await runtime.close()


async def test_catalog_change_during_verification_cannot_create_a_proof(store):
    marker = verification_path(store.data_root).parent / "model-catalog-revision"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"fixture": "before"}))

    class ChangedModel(ProbeModel):
        async def stream(self, messages, tools):
            marker.write_text(json.dumps({"fixture": "after"}))
            yield ModelEvent("text", "OK")

    runtime = Runtime(
        store, ChangedModel(), settings=Settings(endpoint="http://localhost/v1", model="fixture")
    )
    try:
        with pytest.raises(DomainError, match="MODEL_CATALOG_CHANGED"):
            await verify_models(runtime.model_settings, "local")
        assert not runtime.model_settings.view("local")["verified"]
    finally:
        await runtime.close()


@pytest.mark.parametrize("text", ["", "error"])
async def test_failed_verification_revokes_previous_proof_without_changing_settings(store, text):
    model = ProbeModel()
    runtime = Runtime(
        store, model, settings=Settings(endpoint="http://localhost/v1", model="fixture")
    )
    try:
        await verify_models(runtime.model_settings, "local")
        model.text = text
        with pytest.raises(DomainError):
            await verify_models(runtime.model_settings, "local")
        assert not runtime.model_settings.view("local")["verified"]
        assert runtime.settings.model == "fixture"
    finally:
        await runtime.close()
