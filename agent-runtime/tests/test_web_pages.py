import json

import httpx
import pytest

from roami_agent.app import Runtime
from roami_agent.conversation.pages import conversation_page, message_detail
from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.task_list import task_page
from roami_agent.protocol.errors import DomainError
from roami_agent.replies.notification_pages import (
    mark_notifications_read,
    notification_page,
    notification_summary,
)
from roami_agent.replies.notifications import Notifications
from roami_agent.server.http import create_app
from roami_agent.storage.database import event
from roami_agent.storage.transcript_repository import message


async def seed_messages(store, count, text="hello"):
    conversation = await Conversations(store).create("alice")

    def write(db):
        result = []
        for i in range(count):
            mid = message(
                db,
                conversation["id"],
                conversation["active_branch_id"],
                "assistant" if i % 2 else "user",
                {"text": text + str(i)},
            )
            result.append(mid)
            event(db, conversation["id"], "message.completed", {"messageId": mid}, message_id=mid)
        return result

    return conversation, await store.call(write, write=True)


async def test_history_pages_preserve_fork_lineage_and_validate_foreign_cursors(store):
    c, mids = await seed_messages(store, 30)
    fork = await Conversations(store).fork("alice", c["id"], mids[9])
    children = await store.call(
        lambda db: [
            message(db, c["id"], fork["branchId"], "user", {"text": "child"}) for _ in range(5)
        ],
        write=True,
    )
    seen, before = [], None
    while True:
        page = await store.call(
            lambda db, before=before: conversation_page(
                db, "alice", c["id"], fork["branchId"], before=before, limit=7
            )
        )
        assert len(page["messages"]) <= 7
        assert all("content_json" not in m for m in page["messages"])
        seen = [m["id"] for m in page["messages"]] + seen
        before = page["page"]["olderCursor"]
        if not before:
            break
    assert seen == mids[:10] + children
    other, foreign = await seed_messages(store, 1)
    with pytest.raises(DomainError, match="INVALID_MESSAGE_CURSOR"):
        await store.call(lambda db: conversation_page(db, "alice", c["id"], before=foreign[0]))
    with pytest.raises(DomainError, match="CONVERSATION_NOT_FOUND"):
        await store.call(lambda db: conversation_page(db, "bob", other["id"]))


async def test_compact_messages_have_explicit_full_content_and_no_eager_tool_payload(store):
    c, mids = await seed_messages(store, 70, text="long" * 10000)
    await store.call(
        lambda db: message(
            db, c["id"], c["active_branch_id"], "tool", {"text": "tool-secret" * 10000}
        ),
        write=True,
    )
    page = await store.call(lambda db: conversation_page(db, "alice", c["id"], limit=20))
    assert len(page["messages"]) == 20
    assert len(json.dumps(page).encode()) < 100000
    assert all(m["contentTruncated"] for m in page["messages"])
    assert "tool-secret" not in json.dumps(page)
    full = await store.call(lambda db: message_detail(db, "alice", c["id"], mids[-1]))
    assert len(full["content"]["text"]) > 40000
    anchored = await store.call(
        lambda db: conversation_page(db, "alice", c["id"], anchor=mids[10], limit=10)
    )
    assert mids[10] in [m["id"] for m in anchored["messages"]]


async def test_notification_badge_is_small_and_read_all_uses_observed_watermark(store):
    c, _ = await seed_messages(store, 0)
    notices = Notifications(store)
    for i in range(25):
        await notices.publish("alice", c["id"], "notice" * 1000, source="test", dedupe_key=str(i))
    summary = await store.call(lambda db: notification_summary(db, "alice"))
    assert summary["unread"] == 25
    assert len(json.dumps(summary)) < 100
    first = await store.call(lambda db: notification_page(db, "alice", limit=20))
    second = await store.call(
        lambda db: notification_page(db, "alice", limit=20, before=int(first["nextCursor"]))
    )
    assert len(first["items"]) == 20 and len(second["items"]) == 5
    assert "content_json" not in json.dumps(first)
    assert len(first["items"][0]["summary"]) == 180
    await notices.publish("alice", c["id"], "new arrival", source="test", dedupe_key="new")
    await store.call(lambda db: mark_notifications_read(db, "alice", summary["cursor"]), write=True)
    assert (await store.call(lambda db: notification_summary(db, "alice")))["unread"] == 1


async def test_utf8_page_budget_keeps_a_continuous_history_and_visible_activity_anchors(store):
    c, mids = await seed_messages(store, 70, text="正文" * 1500)
    await store.call(
        lambda db: [
            event(
                db,
                c["id"],
                "tool.started",
                {
                    "activity": {
                        "id": "tool:" + mid,
                        "kind": "tool",
                        "name": "shell",
                        "state": "running",
                        "anchorMessageId": mid,
                        "startedMs": i,
                        "updatedMs": i,
                    }
                },
                message_id=mid,
            )
            for i, mid in enumerate(mids)
        ],
        write=True,
    )
    seen, before = [], None
    while True:
        page = await store.call(
            lambda db, before=before: conversation_page(
                db, "alice", c["id"], before=before, limit=70
            )
        )
        assert len(json.dumps(page, ensure_ascii=False).encode()) < 256000
        ids = [m["id"] for m in page["messages"]]
        assert all(a["anchorMessageId"] in ids for a in page["activities"])
        seen = ids + seen
        before = page["page"]["olderCursor"]
        if not before:
            break
    assert seen == mids


async def test_task_list_pages_do_not_return_instruction_or_budget_columns(store):
    c, mids = await seed_messages(store, 1)

    def write(db):
        for i in range(25):
            db.execute(
                "INSERT INTO tasks(id,owner_id,origin_conversation_id,origin_branch_id,origin_message_id,intent_json,state,budget_json,created_ms,updated_ms) VALUES(?,?,?,?,?,?,'queued',?,1,1)",
                (
                    f"t{i:02}",
                    "alice",
                    c["id"],
                    c["active_branch_id"],
                    mids[0],
                    json.dumps(
                        {
                            "title": "Short title",
                            "goal": "large instructions" * 10000,
                            "executor": "native",
                        }
                    ),
                    '{"secret":"budget"}',
                ),
            )

    await store.call(write, write=True)
    first = await store.call(lambda db: task_page(db, "alice", c["id"], limit=20))
    second = await store.call(
        lambda db: task_page(db, "alice", c["id"], before=first["nextCursor"], limit=20)
    )
    assert len(first["items"]) == 20 and len(second["items"]) == 5
    assert {m["id"] for m in first["items"]}.isdisjoint(m["id"] for m in second["items"])
    assert "intent_json" not in json.dumps(first)
    assert "budget" not in json.dumps(first)
    assert len(json.dumps(first).encode()) < 15000
    assert not (await store.call(lambda db: task_page(db, "alice", c["id"], state_filter="ended")))[
        "items"
    ]


async def test_http_paged_history_keeps_legacy_contract_and_validates_limits(store):
    from test_runtime import ConversationModel

    c, _ = await seed_messages(store, 55)
    runtime = Runtime(store, ConversationModel())
    app = create_app(runtime, manage_lifecycle=False)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://agent",
            headers={"X-Roami-Owner": "alice"},
        ) as client:
            legacy = await client.get(f"/v1/conversations/{c['id']}/messages")
            assert len(legacy.json()["data"]["messages"]) == 55
            page = await client.get(f"/v1/conversations/{c['id']}/messages?limit=20")
            assert len(page.json()["data"]["messages"]) == 20
            assert page.json()["data"]["page"]["hasMore"]
            assert (
                await client.get(f"/v1/conversations/{c['id']}/messages?limit=1000")
            ).status_code == 422
            assert (await client.get("/v1/notifications/summary")).status_code == 200
            assert (await client.get("/v1/task-list?limit=0")).status_code == 422
    finally:
        await runtime.close()


async def test_paged_history_does_not_present_an_agent_continuation_plan_as_a_user_request(store):
    c, mids = await seed_messages(store, 25)
    generated = await store.call(
        lambda db: message(
            db,
            c["id"],
            c["active_branch_id"],
            "user",
            {
                "text": "Generated continuation plan",
                "taskSteer": True,
                "sourceUserMessageId": mids[0],
            },
        ),
        write=True,
    )
    page = await store.call(lambda db: conversation_page(db, "alice", c["id"], limit=10))
    assert generated not in [m["id"] for m in page["messages"]]
    assert page["page"]["hasMore"]


async def test_sse_summary_keeps_live_state_without_execution_payloads(store):
    c, mids = await seed_messages(store, 1)
    await store.call(
        lambda db: event(
            db,
            c["id"],
            "tool.started",
            {
                "activity": {
                    "id": "tool:fixture",
                    "kind": "tool",
                    "name": "shell",
                    "state": "running",
                    "anchorMessageId": mids[0],
                    "startedMs": 1,
                    "updatedMs": 1,
                    "preview": {"input": {"text": "large tool arguments" * 1000}, "output": None},
                }
            },
            message_id=mids[0],
        ),
        write=True,
    )
    await store.call(
        lambda db: event(
            db,
            c["id"],
            "message.tool_calls",
            {
                "messageId": mids[0],
                "calls": [{"id": "call", "arguments": "large arguments" * 1000}],
            },
            message_id=mids[0],
        ),
        write=True,
    )
    data = await Conversations(store).events("alice", c["id"], summaries=True)
    item = next(e for e in data if e["kind"] == "tool.started")
    assert item["payload"]["activity"]["state"] == "running"
    assert "preview" not in json.dumps(item)
    assert "payload_json" not in item
    assert next(e for e in data if e["kind"] == "message.tool_calls")["payload"]["calls"] == [
        {"id": "call"}
    ]


async def test_compact_memory_catalog_retains_full_body_only_in_details(store):
    from test_memory_pipeline import source

    from roami_agent.memory.records import Memories

    conversation, receipt, _ = await source(store)
    memories = Memories(store)
    body = "Long source-backed memory. " * 200
    saved = await memories.save(
        "alice", "Memory title", body, receipt["messageId"], conversation_id=conversation["id"]
    )
    page = await memories.catalog.list("alice", compact=True, limit=1)
    assert len(page["items"][0]["body"]) == 200
    assert page["items"][0]["id"] == saved["id"]
    assert "search_tokens" not in page["items"][0]
    assert (await memories.details.get("alice", saved["id"]))["record"]["body"] == body


async def test_scoped_notifications_and_read_cursor_never_cross_conversations(store):
    from test_runtime import ConversationModel

    home, _ = await seed_messages(store, 0)
    project, _ = await seed_messages(store, 0)
    runtime = Runtime(store, ConversationModel())
    own = await runtime.notifications.publish(
        "alice", home["id"], "Home result", source="test", dedupe_key="home"
    )
    await runtime.notifications.publish(
        "alice", project["id"], "Project result", source="test", dedupe_key="project"
    )
    foreign = await runtime.conversations.create("bob")
    app = create_app(runtime, manage_lifecycle=False)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://agent",
            headers={"X-Roami-Owner": "alice"},
        ) as client:
            scoped = (
                await client.get("/v1/notification-list", params={"conversationId": home["id"]})
            ).json()["data"]
            assert len(scoped["items"]) == 1 and scoped["items"][0]["conversation_id"] == home["id"]
            summary = (
                await client.get("/v1/notifications/summary", params={"conversationId": home["id"]})
            ).json()["data"]
            assert summary == {"conversationId": home["id"], "cursor": own["eventId"], "unread": 1}
            assert (
                await client.post(
                    f"/v1/conversations/{home['id']}/read", json={"eventId": own["eventId"]}
                )
            ).status_code == 200
            assert (await runtime.notifications.summary("alice", project["id"]))["unread"] == 1
            for route in ["/v1/notification-list", "/v1/notifications/summary", "/v1/reminders"]:
                assert (
                    await client.get(route, params={"conversationId": foreign["id"]})
                ).status_code == 404
    finally:
        await runtime.close()
