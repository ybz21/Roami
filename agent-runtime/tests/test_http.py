import asyncio
import json

import httpx
import uvicorn
from test_runtime import ConversationModel, until

from roami_agent.runtime import Runtime
from roami_agent.server import create_app
from roami_agent.storage import row


async def test_http_owner_scope_slash_commands_and_task_intent(store):
    runtime = Runtime(store, ConversationModel())
    await runtime.start()
    app = create_app(runtime, manage_lifecycle=False)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://agent",
            headers={"X-Roami-Owner": "alice"},
        ) as client:
            c = (await client.post("/v1/conversations", json={"title": "Main"})).json()["data"]
            response = await client.post(
                f"/v1/conversations/{c['id']}/messages",
                json={"requestKey": "help", "text": "/help"},
            )
            assert response.status_code == 202
            assert len(response.json()["data"]["commands"]) == 6
            assert (await client.get(f"/v1/conversations/{c['id']}/messages")).json()["data"][
                "messages"
            ] == []
            assert (
                await client.post(
                    f"/v1/conversations/{c['id']}/messages",
                    json={"requestKey": "unknown", "text": "/unknown"},
                )
            ).status_code == 400
            forbidden = await client.get(
                f"/v1/conversations/{c['id']}/messages", headers={"X-Roami-Owner": "bob"}
            )
            assert forbidden.status_code == 404
            task = await client.post(
                "/v1/tasks",
                json={
                    "conversationId": c["id"],
                    "requestKey": "task-1",
                    "goal": "Research the topic",
                },
            )
            assert task.status_code == 202
            task_id = task.json()["data"]["id"]
            await until(
                store,
                lambda db: row(
                    db, "SELECT id FROM tasks WHERE id=? AND state='succeeded'", (task_id,)
                ),
            )
            history = (await client.get(f"/v1/conversations/{c['id']}/messages")).json()["data"][
                "messages"
            ]
            assert history[0]["content"]["text"] == "Research the topic"
            again = await client.post(
                "/v1/tasks",
                json={
                    "conversationId": c["id"],
                    "requestKey": "task-1",
                    "goal": "Research the topic",
                },
            )
            assert again.json()["data"]["id"] == task_id
    finally:
        await runtime.close()


async def test_real_unix_http_stream_replays_persisted_events(store, tmp_path):
    runtime = Runtime(store, ConversationModel())
    socket_path = tmp_path / "agent.sock"
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(runtime),
            uds=str(socket_path),
            log_level="error",
            timeout_graceful_shutdown=2,
        )
    )
    running = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(5):
            while not server.started:
                await asyncio.sleep(0.01)
        async with httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=str(socket_path)),
            base_url="http://agent",
            headers={"X-Roami-Owner": "alice"},
            timeout=5,
        ) as client:
            c = (await client.post("/v1/conversations", json={})).json()["data"]
            sent = (
                await client.post(
                    f"/v1/conversations/{c['id']}/messages",
                    json={"requestKey": "one", "text": "hello"},
                )
            ).json()["data"]
            await until(
                store,
                lambda db: row(
                    db, "SELECT id FROM turns WHERE id=? AND state='completed'", (sent["turnId"],)
                ),
            )
            seen, event_ids = [], []
            async with client.stream(
                "GET",
                f"/v1/conversations/{c['id']}/events",
                headers={"Last-Event-ID": str(sent["cursor"])},
            ) as response:
                assert response.status_code == 200
                async for line in response.aiter_lines():
                    if line.startswith("id:"):
                        event_ids.append(int(line[3:]))
                    if line.startswith("data:"):
                        item = json.loads(line[5:])
                        seen.append(item["kind"])
                        if item["kind"] == "message.completed":
                            break
            assert seen == ["message.started", "message.delta", "message.completed"]
            assert all(i > sent["cursor"] for i in event_ids)
            notice = (await client.get("/v1/notifications")).json()["data"]
            assert notice["unread"] == 1
            await client.post(f"/v1/conversations/{c['id']}/read", json={"eventId": event_ids[-1]})
            assert (await client.get("/v1/notifications")).json()["data"]["unread"] == 0
    finally:
        server.should_exit = True
        await running
