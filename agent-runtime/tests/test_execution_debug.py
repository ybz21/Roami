"""Scoped, read-only diagnostics keep queue state separate from history windows."""

import json

import httpx
from test_runtime import ConversationModel, until
from test_task_cancellation import task_run

from roami_agent.app import Runtime
from roami_agent.protocol.identity import now_ms
from roami_agent.server.http import create_app
from roami_agent.storage.database import row


async def test_debug_old_queue_and_off_page_running_task_remain_visible(store, monkeypatch):
    runtime = Runtime(store, ConversationModel())
    try:
        c = await runtime.conversations.create("alice")
        old = await runtime.conversations.accept("alice", c["id"], "old", "old request")
        old_task, _ = await task_run(runtime, c, "old task")
        waiting_task, _ = await task_run(runtime, c, "waiting for approval")

        def age(db):
            db.execute(
                "UPDATE turns SET created_ms=? WHERE id=?", (now_ms() - 172800000, old["turnId"])
            )
            db.execute("UPDATE tasks SET created_ms=1 WHERE id=?", (old_task["id"],))
            db.execute("UPDATE tasks SET state='waiting_user' WHERE id=?", (waiting_task["id"],))

        await store.call(age, write=True)
        fresh = await runtime.conversations.accept("alice", c["id"], "fresh", "fresh request")
        original = store.call

        async def read_only(fn, *, write=False):
            assert not write
            return await original(fn, write=write)

        monkeypatch.setattr(store, "call", read_only)
        view = await runtime.debug.snapshot(
            "alice", c["id"], minutes=15, limit=1, include_context=True
        )
        assert view["requests"]["total"] == 1
        assert view["requests"]["items"][0]["id"] == fresh["turnId"]
        assert view["queue"]["turns"]["total"] == 2
        assert view["queue"]["turns"]["nextOffset"] == 1
        assert view["queue"]["tasks"]["items"][0]["id"] == waiting_task["id"]
        assert view["queue"]["tasks"]["activeTotal"] == 1 and view["active"]
        assert view["context"]["branchId"] == c["active_branch_id"]
        assert "messages" not in view["context"]
        page = await runtime.debug.snapshot(
            "alice", c["id"], queue_offset=1, task_offset=1, limit=1
        )
        assert page["queue"]["turns"]["items"][0]["id"] == old["turnId"]
        assert page["queue"]["tasks"]["items"][0]["id"] == old_task["id"]
        monkeypatch.setattr(store, "call", original)
    finally:
        await runtime.close()


async def test_debug_http_owner_branch_scope_and_forgotten_preview(store):
    runtime = Runtime(store, ConversationModel())
    try:
        c = await runtime.conversations.create("alice")
        other = await runtime.conversations.create("alice")
        receipt = await runtime.conversations.accept("alice", c["id"], "secret", "forgotten secret")
        await store.call(
            lambda db: db.execute(
                "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES(?,?,'test',1)",
                ("alice", receipt["messageId"]),
            ),
            write=True,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
            base_url="http://runtime",
        ) as client:
            endpoint = f"/v1/conversations/{c['id']}/debug"
            headers = {"X-Roami-Owner": "alice"}
            response = await client.get(endpoint, headers=headers)
            assert response.status_code == 200
            assert response.json()["data"]["requests"]["items"][0]["preview"] is None
            assert "forgotten secret" not in response.text
            assert (await client.get(endpoint, headers={"X-Roami-Owner": "bob"})).status_code == 404
            assert (
                await client.get(
                    endpoint, headers=headers, params={"branch": other["active_branch_id"]}
                )
            ).status_code == 404
            assert (
                await client.get(endpoint, headers=headers, params={"minutes": 2})
            ).status_code == 422
            scoped = endpoint + "/trace"
            assert (
                await client.get(
                    scoped,
                    headers=headers,
                    params={"turnId": receipt["turnId"], "branch": other["active_branch_id"]},
                )
            ).status_code == 404
            assert (
                await client.get(
                    scoped, headers=headers, params={"turnId": receipt["turnId"], "taskId": "extra"}
                )
            ).status_code == 400
    finally:
        await runtime.close()


async def test_debug_trace_uses_request_context_and_keeps_legacy_unknown(store):
    runtime = Runtime(store, ConversationModel())
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        other = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "trace", "private body")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
        )
        trace = await runtime.debug.trace("alice", c["id"], turn_id=receipt["turnId"])
        model = next(span for span in trace["spans"] if span["name"] == "model.request")
        assert model["attributes"]["context"]["branchId"] == c["active_branch_id"]
        assert model["attributes"]["limits"]["modelTimeoutSeconds"] == 0
        export = await runtime.debug.trace("alice", c["id"], turn_id=receipt["turnId"], chrome=True)
        assert "private body" not in json.dumps(export)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
            base_url="http://runtime",
        ) as client:
            response = await client.get(
                f"/v1/conversations/{other['id']}/debug/trace",
                params={"turnId": receipt["turnId"]},
                headers={"X-Roami-Owner": "alice"},
            )
            assert response.status_code == 404
        await store.call(
            lambda db: db.execute(
                "UPDATE prompt_manifests SET parts_json=json_remove(parts_json,'$.modelContext','$.requestLimits')"
            ),
            write=True,
        )
        legacy = await runtime.debug.trace("alice", c["id"], turn_id=receipt["turnId"])
        model = next(span for span in legacy["spans"] if span["name"] == "model.request")
        assert model["attributes"]["context"] is None and model["attributes"]["limits"] is None
    finally:
        await runtime.close()
