import asyncio
import json

import pytest

from roami_agent.app import Runtime
from roami_agent.executors import targets
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.database import row
from roami_agent.storage.transcript_repository import history


async def test_tool_start_is_visible_before_result_and_raw_output_is_not_exposed(
    store, monkeypatch
):
    entered, release = asyncio.Event(), asyncio.Event()

    async def query(argv, **kwargs):
        entered.set()
        await release.wait()
        return {"exitCode": 0, "stdout": json.dumps({"data": {"projects": [], "loose": []}})}

    class Model:
        model = "activity-fixture"

        async def stream(self, messages, tools):
            if messages[-1]["role"] == "tool":
                yield ModelEvent("text", "done")
            else:
                yield ModelEvent(
                    "tool",
                    {"id": "lookup", "function": {"name": "workspace_overview", "arguments": "{}"}},
                )

    monkeypatch.setattr(targets, "execute", query)
    runtime = Runtime(store, Model())
    try:
        await runtime.start()
        c = await runtime.conversations.create("alice")
        await runtime.chat.submit("alice", c["id"], "activity", "Count projects")
        await asyncio.wait_for(entered.wait(), 3)
        snapshot = await runtime.conversations.messages("alice", c["id"])
        assert snapshot["activities"][0]["state"] == "running"
        assert snapshot["activities"][0]["name"] == "workspace_overview"
        events = await runtime.conversations.events("alice", c["id"])
        started = next(e for e in events if e["kind"] == "tool.started")
        assert started["payload"]["activity"] == snapshot["activities"][0]
        assert started["payload"]["activity"]["state"] == "running"
        assert not any(e["kind"] == "tool.completed" for e in events)
        release.set()
        from test_runtime import until

        await until(store, lambda db: row(db, "SELECT id FROM tool_calls WHERE state='succeeded'"))
        snapshot = await runtime.conversations.messages("alice", c["id"])
        assert snapshot["activities"][0]["state"] == "succeeded"
        assert "arguments_json" not in json.dumps(snapshot["activities"])
        replay = await runtime.conversations.events("alice", c["id"])
        assert (
            next(e for e in replay if e["id"] == started["id"])["payload"]["activity"]["state"]
            == "running"
        )
        completed = next(e for e in replay if e["kind"] == "tool.completed")
        assert completed["payload"]["activity"] == snapshot["activities"][0]
        assert completed["id"] > started["id"]
    finally:
        release.set()
        await runtime.close()


async def test_failed_completion_has_durable_status_when_context_cannot_build(store):
    from test_runtime import ConversationModel, until

    class RejectingExecutor:
        async def run(self, task, run):
            return {"state": "failed", "summary": "SESSION_NOT_IDLE"}

    runtime = Runtime(store, ConversationModel(), executor=RejectingExecutor())
    build = runtime.loop.context.build

    async def context(turn, instructions, catalog, completion):
        if completion:
            raise DomainError("CONTEXT_TOO_LARGE")
        return await build(turn, instructions, catalog, completion)

    runtime.loop.context.build = context
    try:
        c = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            c["id"],
            "Continue",
            key="rejected",
            executor="codex",
            target={"kind": "session", "sessionId": "known"},
            record_intent=True,
        )
        await runtime.start()
        await until(
            store,
            lambda db: row(
                db,
                "SELECT id FROM messages WHERE json_extract(content_json,'$.taskStatus.taskId')=?",
                (task["id"],),
            ),
        )
        snapshot = await runtime.conversations.messages("alice", c["id"])
        status = next(
            m["content"]["taskStatus"] for m in snapshot["messages"] if "taskStatus" in m["content"]
        )
        assert status == {
            "taskId": task["id"],
            "state": "failed",
            "errorCode": "SESSION_NOT_IDLE",
            "reportError": "CONTEXT_TOO_LARGE",
        }
        assert snapshot["activities"][0]["state"] == "failed"
        assert snapshot["activities"][0]["delivered"] is False
        from roami_agent.context.projection import model_messages

        text = json.dumps(
            model_messages(await store.call(lambda db: history(db, c["active_branch_id"])))
        )
        assert "SESSION_NOT_IDLE" in text
    finally:
        await runtime.close()


async def test_conflicting_session_override_is_rejected_before_queueing(store):
    from roami_agent.conversation.transcript import Conversations
    from roami_agent.dispatch.tasks import Tasks

    c = await Conversations(store).create("alice")
    with pytest.raises(DomainError, match="CODING_SESSION_TARGET_CONFLICT"):
        await Tasks(store, Conversations(store)).create(
            "alice",
            c["id"],
            "work",
            key="bad",
            executor="codex",
            target={"kind": "session", "sessionId": "exact", "directory": "/wrong"},
            record_intent=True,
        )
    assert await store.call(lambda db: db.execute("SELECT count(*) FROM tasks").fetchone()[0]) == 0


async def test_worker_tool_activity_reaches_origin_conversation_while_running(store):
    entered, release = asyncio.Event(), asyncio.Event()

    class Model:
        model = "nested-activity-fixture"

        async def stream(self, messages, tools):
            worker = messages[0]["content"].startswith("Complete the delegated goal")
            if worker and messages[-1]["role"] != "tool":
                name, args = "memory_search", {"query": "fixture"}
            elif messages[-1]["content"] == "Delegate read only":
                name, args = "delegate", {"goal": "Recall a memory, then answer briefly"}
            else:
                yield ModelEvent("text", "Read-only result recorded")
                return
            yield ModelEvent(
                "tool", {"id": name, "function": {"name": name, "arguments": json.dumps(args)}}
            )

    runtime = Runtime(store, Model())

    async def recall(*args, **kwargs):
        entered.set()
        await release.wait()
        return {"hits": [], "truncated": False}

    runtime.memory.recall = recall
    try:
        await runtime.start()
        c = await runtime.conversations.create("alice")
        await runtime.chat.submit("alice", c["id"], "nested", "Delegate read only")
        await asyncio.wait_for(entered.wait(), 4)
        view = await runtime.conversations.messages("alice", c["id"])
        child = next(a for a in view["activities"] if a["name"] == "memory_search")
        assert child["state"] == "running" and child["taskId"]
        assert child["anchorMessageId"] in {m["id"] for m in view["messages"]}
        events = await runtime.conversations.events("alice", c["id"])
        bubbled = next(
            e
            for e in events
            if e["kind"] == "task.activity" and e["payload"].get("toolName") == "memory_search"
        )
        assert bubbled["payload"]["activity"] == child
        assert bubbled["branchId"] == view["branchId"]
        assert any(
            e["kind"] == "task.started"
            and e["branchId"] == view["branchId"]
            and e["payload"].get("activity", {}).get("kind") == "task"
            for e in events
        )
        assert any(
            e["kind"] == "task.activity" and e["payload"]["toolName"] == "memory_search"
            for e in events
        )
    finally:
        release.set()
        await runtime.close()


async def test_delegate_receipt_does_not_repeat_goal_or_claim_delivery():
    from roami_agent.tools.main_catalog import register_main_tools
    from roami_agent.tools.registry import Tools

    class TaskStore:
        async def create(self, *args, **kwargs):
            return {
                "id": "accepted-task",
                "state": "queued",
                "intent_json": json.dumps({"goal": "large private goal", "executor": "native"}),
                "budget_json": "internal",
            }

    tools = Tools()
    register_main_tools(tools, TaskStore(), None, None)
    value = await tools.invoke(
        {"id": "call", "function": {"name": "delegate", "arguments": json.dumps({"goal": "work"})}},
        "main",
        {
            "owner": "alice",
            "conversation": "conversation",
            "turnId": "turn",
            "toolCallId": "call",
            "assistantMessageId": "assistant",
            "originMessageId": "user",
        },
    )
    assert value == {
        "id": "accepted-task",
        "taskId": "accepted-task",
        "kind": "background_task",
        "executor": "native",
        "state": "queued",
        "acceptedOnly": True,
        "delivery": "pending",
    }


async def test_command_nonzero_exit_is_failed_in_live_events_and_history(store):
    from roami_agent.conversation.activity_events import activity_event
    from roami_agent.conversation.transcript import Conversations
    from roami_agent.storage.transcript_repository import message

    conversations = Conversations(store)
    c = await conversations.create("alice")
    receipt = await conversations.accept("alice", c["id"], "command", "Run a command")

    def record(db):
        mid = message(
            db,
            c["id"],
            c["active_branch_id"],
            "assistant",
            {"text": "Checking"},
            turn_id=receipt["turnId"],
        )
        result = message(
            db,
            c["id"],
            c["active_branch_id"],
            "tool",
            {"text": json.dumps({"exitCode": 7, "stderr": "private output"})},
            turn_id=receipt["turnId"],
        )
        db.execute(
            "INSERT INTO tool_calls(id,turn_id,assistant_message_id,tool_name,arguments_json,effect,state,idempotency_key,result_message_id,created_ms,updated_ms) VALUES('command',?,?,'shell','{}','write','succeeded','command-key',?,1,2)",
            (receipt["turnId"], mid, result),
        )
        activity_event(
            db,
            c["id"],
            "tool.completed",
            {"toolCallId": "command", "toolName": "shell", "state": "succeeded"},
            turn_id=receipt["turnId"],
        )

    await store.call(record, write=True)
    snapshot = await conversations.messages("alice", c["id"])
    activity = snapshot["activities"][0]
    assert activity["state"] == "failed"
    assert activity["errorCode"] == "COMMAND_EXIT_NONZERO"
    assert "private output" not in json.dumps(activity)
    events = await conversations.events("alice", c["id"])
    assert events[-1]["payload"]["activity"] == activity


async def test_payload_details_are_owner_scoped_live_and_not_in_events(store, monkeypatch):
    import httpx
    from test_runtime import until

    from roami_agent.server.http import create_app

    entered, release = asyncio.Event(), asyncio.Event()

    async def query(argv, **kwargs):
        entered.set()
        await release.wait()
        return {"exitCode": 0, "stdout": json.dumps({"data": {"projects": [], "loose": []}})}

    class Model:
        model = "payload-fixture"

        async def stream(self, messages, tools):
            if messages[-1]["role"] == "tool":
                yield ModelEvent("text", "done")
            else:
                yield ModelEvent(
                    "tool",
                    {"id": "lookup", "function": {"name": "workspace_overview", "arguments": "{}"}},
                )

    monkeypatch.setattr(targets, "execute", query)
    runtime = Runtime(store, Model())
    try:
        await runtime.start()
        conversation = await runtime.conversations.create("alice")
        await runtime.chat.submit("alice", conversation["id"], "details", "Count projects")
        await asyncio.wait_for(entered.wait(), 3)
        snapshot = await runtime.conversations.messages("alice", conversation["id"])
        activity = snapshot["activities"][0]
        path = f"/v1/conversations/{conversation['id']}/activities/{activity['id']}"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
            base_url="http://agent",
            headers={"X-Roami-Owner": "alice"},
        ) as client:
            running = (await client.get(path)).json()["data"]
            assert running["output"] is None
            assert running["input"]["text"] == "{}"
            assert (await client.get(path, headers={"X-Roami-Owner": "bob"})).status_code == 404
            assert (await client.get(path + "?branchId=foreign")).status_code == 404
            assert (
                await client.get(path.replace(activity["id"], "tool:foreign"))
            ).status_code == 404
            release.set()
            await until(
                store, lambda db: row(db, "SELECT id FROM tool_calls WHERE state='succeeded'")
            )
            completed = (await client.get(path)).json()["data"]
            assert completed["state"] == "succeeded" and completed["output"] is not None
            assert not any(
                "input" in event["payload"].get("activity", {})
                for event in await runtime.conversations.events("alice", conversation["id"])
            )
            await store.call(
                lambda db: db.execute(
                    "UPDATE messages SET status='deleted' WHERE id=(SELECT result_message_id FROM tool_calls LIMIT 1)"
                ),
                write=True,
            )
            assert (await client.get(path)).status_code == 404
    finally:
        release.set()
        await runtime.close()


def test_payload_preview_redacts_credentials_and_bounds_large_content():
    from roami_agent.conversation.activity_payloads import preview

    result = preview(
        {
            "headers": {"Authorization": "Bearer example", "Cookie": "private"},
            "api_key": "private",
            "imageBase64": "private",
            "text": "sk-012345678901234567890123",
            "nested": ["Bearer ABCDEFGHIJKLMNOP"],
            "large": "x" * 20000,
        }
    )
    assert "private" not in result["text"]
    assert "0123456789" not in result["text"]
    assert "ABCDEFGHIJKLMNOP" not in result["text"]
    assert result["truncated"] and len(result["text"]) == 16000
