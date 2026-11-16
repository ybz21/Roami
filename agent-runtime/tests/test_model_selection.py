"""A session model is durable, isolated from defaults, and admitted by the gateway."""

import json
from dataclasses import asdict

import pytest
from test_local_go_gateway import gateway_fixture
from test_model_proxy import consume

from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.tasks import Tasks
from roami_agent.protocol.errors import DomainError
from roami_agent.providers.factory import configured_provider
from roami_agent.providers.model_selection import ModelSelections
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


async def test_conversation_selection_is_durable_and_part_of_idempotency(store):
    conversations = Conversations(store)
    first = await conversations.create(
        "owner", "Free work", request_key="new", model="free-pool", free_only=True
    )
    replay = await conversations.create(
        "owner", "Free work", request_key="new", model="free-pool", free_only=True
    )
    assert replay["id"] == first["id"]
    with pytest.raises(DomainError, match="REQUEST_KEY_CONFLICT"):
        await conversations.create("owner", "Free work", request_key="new", model="paid-model")
    choice = await store.call(
        lambda db: row(
            db, "SELECT * FROM conversation_models WHERE conversation_id=?", (first["id"],)
        )
    )
    assert choice["model"] == "free-pool" and choice["free_only"] == 1
    assert len(await conversations.list("owner")) == 1


async def test_native_task_validates_before_creating_resources_and_keeps_model(store):
    conversations = Conversations(store)
    main = await conversations.create("owner")
    tasks = Tasks(store, conversations)

    class Selector:
        rejected = True

        async def validate(self, model, free_only, role):
            assert (model, free_only, role) == ("free-pool", True, "worker")
            if self.rejected:
                raise DomainError("MODEL_NOT_CONFIGURED")

    selector = Selector()
    tasks.model_selections = selector
    options = {"key": "job", "model": "free-pool", "free_only": True, "record_intent": True}
    with pytest.raises(DomainError, match="MODEL_NOT_CONFIGURED"):
        await tasks.create("owner", main["id"], "Review", **options)
    assert await store.call(lambda db: db.execute("SELECT count(*) FROM tasks").fetchone()[0]) == 0
    selector.rejected = False
    task = await tasks.create("owner", main["id"], "Review", **options)
    replay = await tasks.create("owner", main["id"], "Review", **options)
    assert replay["id"] == task["id"]
    detail = await tasks.get("owner", task["id"])
    cid = detail["task"]["nativeSession"]["conversationId"]
    choice = await store.call(
        lambda db: row(db, "SELECT * FROM conversation_models WHERE conversation_id=?", (cid,))
    )
    assert choice["model"] == "free-pool" and choice["free_only"] == 1
    assert json.loads(task["intent_json"])["freeOnly"] is True


async def test_selected_provider_forwards_binding_and_does_not_mutate_settings(tmp_path):
    socket = str(tmp_path / "gateway.sock")
    settings = Settings(
        endpoint="https://never-connect.invalid/v1",
        model="default-main",
        worker_model="default-worker",
        model_gateway_socket=socket,
    )
    before = asdict(settings)
    selection = {
        "model": "free-pool",
        "revision": "catalog-revision",
        "freeOnly": True,
        "routeId": "role-route",
    }
    seen = []
    async with gateway_fixture(socket, seen):
        chosen = configured_provider(settings, "worker", selection=selection)
        try:
            await consume(chosen)
        finally:
            await chosen.close()
    _, headers, payload = seen[0]
    assert payload["model"] == "free-pool"
    assert headers["x-roami-model-selection"] == "free-pool"
    assert headers["x-roami-model-revision"] == "catalog-revision"
    assert headers["x-roami-free-only"] == "true"
    assert headers["x-roami-model-route"] == "role-route"
    assert asdict(settings) == before


async def test_selected_provider_is_resolved_per_conversation(store):
    settings = Settings(
        endpoint="https://never-connect.invalid/v1",
        model="default",
        model_gateway_socket="/unavailable",
    )
    conversations = Conversations(store)
    chosen = await conversations.create("owner", model="free-pool", free_only=True)
    default = await conversations.create("owner")
    selections = ModelSelections(store, settings)
    seen = []

    async def resolve(model, free_only, role):
        seen.append((model, free_only, role))
        return {"model": model, "freeOnly": free_only, "revision": "r1", "routeId": "bound"}

    selections.validate = resolve
    provider = await selections.provider({"conversation_id": chosen["id"]}, "main")
    try:
        assert provider.model == "free-pool"
        assert await selections.provider({"conversation_id": default["id"]}, "main") is None
        assert seen == [("free-pool", True, "main")]
    finally:
        await provider.close()


async def test_native_session_http_is_idempotent_and_owned(store):
    import httpx
    from test_runtime import ConversationModel

    from roami_agent.app import Runtime
    from roami_agent.server.http import create_app

    runtime = Runtime(store, ConversationModel())

    async def validate(model, free_only=False, role="main"):
        if model == "missing":
            raise DomainError("MODEL_NOT_CONFIGURED", 400)
        return {"model": model, "freeOnly": free_only, "revision": "r1", "routeId": "bound"}

    runtime.model_selections.validate = validate
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime)),
            base_url="http://test",
            headers={"X-Roami-Owner": "alice"},
        ) as client:
            rejected = await client.post(
                "/v1/native-sessions",
                json={"requestKey": "bad", "task": "Review", "model": "missing"},
            )
            assert rejected.status_code == 400
            assert await runtime.conversations.list("alice") == []
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
            cid = receipt["conversationId"]
            choice = await client.get(f"/v1/conversations/{cid}/model")
            assert choice.json()["data"] == {"model": "free-pool", "freeOnly": True}
            assert (
                await client.get(f"/v1/conversations/{cid}/model", headers={"X-Roami-Owner": "bob"})
            ).status_code == 404
            assert (
                await client.put(f"/v1/conversations/{cid}/model", json={"model": "other"})
            ).status_code == 409
    finally:
        await runtime.close()
