import httpx
from test_runtime import ConversationModel, until

from roami_agent.app import Runtime
from roami_agent.server.http import create_app
from roami_agent.storage.database import row


def _turn_done(turn_id):
    return lambda db: (
        (t := row(db, "SELECT state FROM turns WHERE id=?", (turn_id,))) is not None
        and t["state"] == "completed"
    )


async def test_delete_message_removes_from_history_context_and_emits_event(store):
    runtime = Runtime(store, ConversationModel())
    app = create_app(runtime, manage_lifecycle=False)
    await runtime.start()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://agent",
            headers={"X-Roami-Owner": "local"},
        ) as client:
            conv = (await client.post("/v1/main-conversation")).json()["data"]
            cid = conv["id"]
            first = (
                await client.post(
                    f"/v1/conversations/{cid}/messages",
                    json={"requestKey": "m1", "text": "Hello one"},
                )
            ).json()["data"]
            await until(store, _turn_done(first["turnId"]))

            second = (
                await client.post(
                    f"/v1/conversations/{cid}/messages",
                    json={"requestKey": "m2", "text": "Hello two"},
                )
            ).json()["data"]
            await until(store, _turn_done(second["turnId"]))

            page = (await client.get(f"/v1/conversations/{cid}/messages?limit=50")).json()["data"]
            assert len(page["messages"]) == 4
            user_id = page["messages"][0]["id"]
            assistant_id = page["messages"][1]["id"]
            epoch_before = (
                await store.call(
                    lambda db: row(
                        db, "SELECT epoch FROM branches WHERE id=?", (conv["active_branch_id"],)
                    )
                )
            )["epoch"]

            deleted = await client.delete(f"/v1/conversations/{cid}/messages/{assistant_id}")
            assert deleted.status_code == 200
            assert deleted.json()["data"] == {"messageId": assistant_id, "deleted": True}

            # Deleting an already-deleted message is idempotent.
            again = await client.delete(f"/v1/conversations/{cid}/messages/{assistant_id}")
            assert again.status_code == 200
            assert again.json()["data"] == {"messageId": assistant_id, "deleted": True}

            # Deleting a user message also works.
            deleted_user = await client.delete(f"/v1/conversations/{cid}/messages/{user_id}")
            assert deleted_user.status_code == 200

            after_page = (await client.get(f"/v1/conversations/{cid}/messages?limit=50")).json()[
                "data"
            ]
            remaining_ids = [m["id"] for m in after_page["messages"]]
            assert user_id not in remaining_ids
            assert assistant_id not in remaining_ids
            assert len(remaining_ids) == 2

            # Detail endpoint returns 404 for deleted messages.
            detail = await client.get(f"/v1/conversations/{cid}/messages/{assistant_id}")
            assert detail.status_code == 404

            # Context projection excludes deleted messages and branch epoch advanced.
            plan = await runtime.context.project("local", cid)
            assert user_id not in plan["sourceMessageIds"]
            assert assistant_id not in plan["sourceMessageIds"]
            epoch_after = (
                await store.call(
                    lambda db: row(
                        db, "SELECT epoch FROM branches WHERE id=?", (conv["active_branch_id"],)
                    )
                )
            )["epoch"]
            assert epoch_after == epoch_before + 2

            # Committed event stream contains message.deleted events.
            events = await runtime.conversations.events("local", cid, 0, summaries=True)
            deleted_events = [e for e in events if e["kind"] == "message.deleted"]
            assert {e["payload"]["messageId"] for e in deleted_events} == {user_id, assistant_id}
    finally:
        await runtime.close()


async def test_delete_message_rejects_active_turn_and_active_task(store):
    runtime = Runtime(store, ConversationModel())
    app = create_app(runtime, manage_lifecycle=False)
    await runtime.start()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://agent",
            headers={"X-Roami-Owner": "local"},
        ) as client:
            conv = (await client.post("/v1/main-conversation")).json()["data"]
            cid = conv["id"]
            sent = (
                await client.post(
                    f"/v1/conversations/{cid}/messages",
                    json={"requestKey": "m1", "text": "Start work"},
                )
            ).json()["data"]
            await until(store, _turn_done(sent["turnId"]))

            # Simulate a running turn on the branch -> 409 BRANCH_BUSY.
            await store.call(
                lambda db: db.execute(
                    "UPDATE turns SET state='running' WHERE id=?", (sent["turnId"],)
                ),
                write=True,
            )
            busy = await client.delete(f"/v1/conversations/{cid}/messages/{sent['messageId']}")
            assert busy.status_code == 409
            assert busy.json()["error"]["code"] == "BRANCH_BUSY"

            # Restore completed turn, attach an active task -> 409 MESSAGE_HAS_ACTIVE_TASK.
            await store.call(
                lambda db: db.execute(
                    "UPDATE turns SET state='completed' WHERE id=?", (sent["turnId"],)
                ),
                write=True,
            )
            await store.call(
                lambda db: db.execute(
                    "INSERT INTO tasks(id,owner_id,origin_conversation_id,origin_branch_id,origin_message_id,"
                    "revision,intent_json,state,budget_json,created_ms,updated_ms) "
                    "VALUES('t-active','local',?,?,?,1,'{\"executor\":\"native\",\"goal\":\"work\"}','running','{}',1,1)",
                    (cid, conv["active_branch_id"], sent["messageId"]),
                ),
                write=True,
            )
            active_task = await client.delete(
                f"/v1/conversations/{cid}/messages/{sent['messageId']}"
            )
            assert active_task.status_code == 409
            assert active_task.json()["error"]["code"] == "MESSAGE_HAS_ACTIVE_TASK"

            # Unknown message returns 404.
            missing = await client.delete(f"/v1/conversations/{cid}/messages/nonexistent")
            assert missing.status_code == 404
    finally:
        await runtime.close()
