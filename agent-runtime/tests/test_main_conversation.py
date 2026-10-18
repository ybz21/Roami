"""The app binds one persistent Main per owner without deleting older records."""

import asyncio

import httpx

from roami_agent.app import Runtime
from roami_agent.conversation.transcript import Conversations
from roami_agent.server.http import create_app


async def test_concurrent_main_intake_and_restart_preserve_one_identity(store):
    service = Conversations(store)
    results = await asyncio.gather(*(service.main("alice") for _ in range(20)))
    cid = results[0]["id"]
    assert {value["id"] for value in results} == {cid}
    assert len(await service.list("alice")) == 1
    assert (await Conversations(store).main("alice"))["id"] == cid
    assert (await service.main("bob"))["id"] != cid


async def test_existing_roots_are_preserved_and_new_records_do_not_replace_main(store):
    service = Conversations(store)
    first = await service.create("alice", "Earlier")
    second = await service.create("alice", "Later")
    await store.call(
        lambda db: db.execute(
            "UPDATE conversations SET created_ms=created_ms-1000 WHERE id=?", (first["id"],)
        ),
        write=True,
    )
    assert (await service.main("alice"))["id"] == first["id"]
    await service.create("alice", "Legacy external record")
    assert (await service.main("alice"))["id"] == first["id"]
    assert (await service.get("alice", second["id"]))["title"] == "Later"
    assert len(await service.list("alice")) == 3


async def test_main_endpoint_is_idempotent_and_owner_scoped(store):
    from test_runtime import ConversationModel

    runtime = Runtime(store, ConversationModel())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
        base_url="http://agent",
    ) as client:
        first = await client.post("/v1/main-conversation", headers={"X-Roami-Owner": "alice"})
        again = await client.post("/v1/main-conversation", headers={"X-Roami-Owner": "alice"})
        other = await client.post("/v1/main-conversation", headers={"X-Roami-Owner": "bob"})
        assert first.status_code == again.status_code == other.status_code == 200
        assert first.json()["data"]["id"] == again.json()["data"]["id"]
        assert other.json()["data"]["id"] != first.json()["data"]["id"]
