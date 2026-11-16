"""Native tasks reuse their saved intent and the existing provider connection."""

import asyncio
import json
from copy import copy
from dataclasses import asdict

import httpx
from test_local_go_gateway import gateway_fixture
from test_model_proxy import consume
from test_runtime import ConversationModel, until

from roami_agent.app import Runtime
from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.tasks import Tasks
from roami_agent.providers.factory import configured_provider
from roami_agent.server.configuration import Settings
from roami_agent.server.http import create_app
from roami_agent.storage.database import row


async def test_native_model_is_saved_in_existing_task_intent(store):
    conversations = Conversations(store)
    main = await conversations.create("owner")
    tasks = Tasks(store, conversations)
    options = {"key": "job", "model": "free-pool", "free_only": True, "record_intent": True}
    task = await tasks.create("owner", main["id"], "Review", **options)
    replay = await tasks.create("owner", main["id"], "Review", **options)
    assert replay["id"] == task["id"]
    saved = await store.call(lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],)))
    intent = json.loads(saved["intent_json"])
    assert intent["model"] == "free-pool" and intent["freeOnly"] is True
    assert (await tasks.get("owner", task["id"]))["task"]["nativeSession"]["conversationId"]


async def test_parallel_model_choices_share_connection_without_mutating_default(tmp_path):
    settings = Settings(
        endpoint="https://never-connect.invalid/v1",
        model="default-main",
        worker_model="default-worker",
        model_gateway_socket=str(tmp_path / "gateway.sock"),
    )
    before = asdict(settings)
    provider = configured_provider(settings, "worker")
    first = provider.with_model("free-pool", free_only=True)
    second = provider.with_model("other-model")
    assert first.client is second.client is provider.client
    assert first.provider_key == second.provider_key == provider.provider_key
    assert first.settings_hash != second.settings_hash != provider.settings_hash
    seen = []
    try:
        async with gateway_fixture(settings.model_gateway_socket, seen):
            await asyncio.gather(consume(first), consume(second), consume(provider))
    finally:
        await provider.close()
    calls = {payload["model"]: (headers, payload) for _, headers, payload in seen}
    assert set(calls) == {"free-pool", "other-model", "default-worker"}
    assert calls["free-pool"][1]["roami_free_only"] is True
    for model in ("other-model", "default-worker"):
        assert "roami_free_only" not in calls[model][1]
    for headers, _ in calls.values():
        assert "x-roami-model-selection" not in headers
        assert "x-roami-model-revision" not in headers
        assert "x-roami-free-only" not in headers
    assert provider.model == "default-worker" and asdict(settings) == before
    assert provider.with_model("auto").model == "default-worker"


async def test_native_task_execution_receives_selected_model(store):
    class SelectedModel(ConversationModel):
        def __init__(self):
            self.seen = []

        def with_model(self, model, *, free_only=False):
            selected = copy(self)
            selected.model = model
            selected.free_only = free_only
            return selected

        async def stream(self, messages, tools):
            self.seen.append((self.model, getattr(self, "free_only", False)))
            async for event in super().stream(messages, tools):
                yield event

    provider = SelectedModel()
    runtime = Runtime(store, provider)
    await runtime.start()
    try:
        main = await runtime.conversations.create("owner")
        task = await runtime.tasks.create(
            "owner",
            main["id"],
            "Read facts",
            key="job",
            model="free-pool",
            free_only=True,
            target={"kind": "new_session"},
            record_intent=True,
        )
        runtime.wakeup.set()
        await until(
            store,
            lambda db: row(
                db,
                "SELECT id FROM tasks WHERE id=? AND state IN ('succeeded','failed')",
                (task["id"],),
            ),
        )
        detail = await runtime.tasks.get("owner", task["id"])
        assert detail["task"]["state"] == "succeeded", detail
        assert ("free-pool", True) in provider.seen
        assert provider.model == "injected-model"
    finally:
        await runtime.close()


async def test_native_session_http_is_idempotent_and_owned(store):
    runtime = Runtime(store, ConversationModel())
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime)),
            base_url="http://test",
            headers={"X-Roami-Owner": "alice"},
        ) as client:
            payload = {
                "requestKey": "job",
                "title": "Review",
                "task": "Read facts",
                "model": "free-pool",
                "freeOnly": True,
            }
            response = await client.post("/v1/native-sessions", json=payload)
            assert response.status_code == 202, response.text
            receipt = response.json()["data"]
            assert receipt["session"].startswith("roami:")
            assert (
                await client.post("/v1/native-sessions", json=payload)
            ).json() == response.json()
            detail = await runtime.tasks.get("alice", receipt["taskId"])
            assert json.loads(detail["task"]["intent_json"])["model"] == "free-pool"
            assert (
                await client.get(
                    f"/v1/native-sessions/{receipt['session'][6:]}",
                    headers={"X-Roami-Owner": "bob"},
                )
            ).status_code == 404
    finally:
        await runtime.close()
