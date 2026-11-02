import asyncio
import json

import pytest

from roami_agent.app import Runtime
from roami_agent.executors import targets
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.database import row
from roami_agent.storage.transcript_repository import history


async def test_tool_start_and_completion_replay_previews_before_the_final_reply(store, monkeypatch):
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
        assert len(snapshot["activities"]) == 1
        events = await runtime.conversations.events("alice", c["id"])
        started = next(e for e in events if e["kind"] == "tool.started")
        assert started["payload"]["activity"]["name"] == "workspace_overview"
        assert started["payload"]["activity"]["state"] == "running"
        assert not any(e["kind"] == "tool.completed" for e in events)
        release.set()
        from test_runtime import until

        await until(store, lambda db: row(db, "SELECT id FROM tool_calls WHERE state='succeeded'"))
        snapshot = await runtime.conversations.messages("alice", c["id"])
        assert len(snapshot["activities"]) == 1
        assert "arguments_json" not in json.dumps(snapshot["activities"])
        replay = await runtime.conversations.events("alice", c["id"])
        assert (
            next(e for e in replay if e["id"] == started["id"])["payload"]["activity"]["state"]
            == "running"
        )
        completed = next(e for e in replay if e["kind"] == "tool.completed")
        assert completed["payload"]["activity"]["state"] == "succeeded"
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


async def test_worker_tools_stream_into_main_with_task_scoped_details(store):
    entered, release = asyncio.Event(), asyncio.Event()

    class Model:
        model = "nested-activity-fixture"

        async def stream(self, messages, tools):
            worker = messages[0]["content"].startswith("Complete the delegated goal")
            if worker and messages[-1]["role"] != "tool":
                name, args = "memory_search", {"query": "fixture"}
            elif messages[-1]["content"] == "Delegate read only":
                name, args = (
                    "delegate",
                    {"requestComplete": False, "goal": "Recall a memory, then answer briefly"},
                )
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
        assert any(a["name"] == "memory_search" for a in view["activities"])
        root = next(a for a in view["activities"] if a["kind"] == "task")
        records = await runtime.tasks.activities("alice", root["taskId"])
        child = next(a for a in records if a["name"] == "memory_search")
        detail = await runtime.tasks.get("alice", root["taskId"])
        run_id = detail["attempts"][0]["id"]
        assert detail["attempts"][0]["hasConversation"] is True
        worker = await runtime.tasks.conversation("alice", root["taskId"], run_id)
        assert worker["conversation"]["id"] != c["id"]
        assert all(m["role"] in {"user", "assistant"} for m in worker["messages"])
        import httpx

        from roami_agent.server.http import create_app

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
            base_url="http://agent",
            headers={"X-Roami-Owner": "alice"},
        ) as client:
            base = f"/v1/tasks/{root['taskId']}"
            assert (await client.get(base + "/activities")).status_code == 200
            payload = await client.get(base + "/activities/" + child["id"])
            assert (
                payload.status_code == 200 and "fixture" in payload.json()["data"]["input"]["text"]
            )
            for suffix in [
                "/activities",
                "/activities/" + child["id"],
                "/conversation?runId=" + run_id,
            ]:
                assert (
                    await client.get(base + suffix, headers={"X-Roami-Owner": "bob"})
                ).status_code == 404
            assert (await client.get(base + "/activities/tool:foreign")).status_code == 404
            main_tool = await store.call(
                lambda db: row(
                    db,
                    "SELECT tc.id FROM tool_calls tc JOIN turns t ON t.id=tc.turn_id WHERE t.conversation_id=? LIMIT 1",
                    (c["id"],),
                )
            )
            assert (
                await client.get(base + "/activities/tool:" + main_tool["id"])
            ).status_code == 404
            assert (await client.get(base + "/conversation?runId=foreign")).status_code == 404
            assert (await client.get(base + "/conversation?runId=" + run_id)).json()["data"][
                "messages"
            ] == worker["messages"]
            other = await runtime.tasks.create(
                "alice", c["id"], "Another task", key="other-task", record_intent=True
            )
            other_detail = await runtime.tasks.get("alice", other["id"])
            other_run = other_detail["attempts"][0]["id"]
            assert (await client.get(base + "/conversation?runId=" + other_run)).status_code == 404
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
        source = (await runtime.tasks.get("alice", root["taskId"]))["task"]["origin_message_id"]
        await store.call(
            lambda db: db.execute("UPDATE messages SET status='deleted' WHERE id=?", (source,)),
            write=True,
        )
        with pytest.raises(DomainError, match="TASK_SOURCE_FORGOTTEN"):
            await runtime.tasks.conversation("alice", root["taskId"], run_id)
        assert await runtime.tasks.activities("alice", root["taskId"]) == []
    finally:
        release.set()
        await runtime.close()


async def test_delegate_receipt_does_not_repeat_goal_or_claim_delivery(store):
    from roami_agent.tools.main_catalog import register_main_tools
    from roami_agent.tools.registry import Tools

    class TaskStore:
        db = store

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
        {
            "id": "call",
            "function": {
                "name": "delegate",
                "arguments": json.dumps({"requestComplete": False, "goal": "work"}),
            },
        },
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
        "requestComplete": False,
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
            {"text": json.dumps({"exitCode": 7, "stderr": "fixture command error"})},
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
    assert len(snapshot["activities"]) == 1
    events = await conversations.events("alice", c["id"])
    activity = events[-1]["payload"]["activity"]
    assert activity["state"] == "failed"
    assert activity["errorCode"] == "COMMAND_EXIT_NONZERO"
    assert "fixture command error" in activity["preview"]["output"]["text"]
    events = await conversations.events("alice", c["id"])
    assert events[-1]["payload"]["activity"] == activity


async def test_payload_previews_stream_with_owner_scoped_full_details(store, monkeypatch):
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
        assert len(snapshot["activities"]) == 1
        events = await runtime.conversations.events("alice", conversation["id"])
        activity = next(e["payload"]["activity"] for e in events if e["kind"] == "tool.started")
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
            replay = await runtime.conversations.events("alice", conversation["id"])
            completed_event = next(e for e in replay if e["kind"] == "tool.completed")
            assert completed_event["payload"]["activity"]["preview"]["input"] == completed["input"]
            assert (
                completed_event["payload"]["activity"]["preview"]["output"] == completed["output"]
            )
            await store.call(
                lambda db: db.execute(
                    "UPDATE messages SET status='deleted' WHERE id=(SELECT result_message_id FROM tool_calls LIMIT 1)"
                ),
                write=True,
            )
            assert (await client.get(path)).status_code == 404
            replay = await runtime.conversations.events("alice", conversation["id"])
            assert not any(e["payload"].get("activity", {}).get("preview") for e in replay)
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


async def test_streamed_previews_redact_and_bound_both_inputs_and_results(store):
    from roami_agent.conversation.activity_events import activity_event
    from roami_agent.conversation.transcript import Conversations
    from roami_agent.storage.transcript_repository import message

    conversations = Conversations(store)
    c = await conversations.create("alice")
    receipt = await conversations.accept("alice", c["id"], "preview", "Inspect a fixture")

    def record(db):
        mid = message(
            db,
            c["id"],
            c["active_branch_id"],
            "assistant",
            {"text": "Inspecting"},
            turn_id=receipt["turnId"],
        )
        arguments = {"Authorization": "private-input", "query": "x" * 5000}
        output = {"Cookie": "private-output", "data": "x" * 10000}
        result = message(
            db,
            c["id"],
            c["active_branch_id"],
            "tool",
            {"text": json.dumps(output)},
            turn_id=receipt["turnId"],
        )
        db.execute(
            "INSERT INTO tool_calls(id,turn_id,assistant_message_id,tool_name,arguments_json,effect,state,idempotency_key,result_message_id,created_ms,updated_ms) VALUES('preview',?,?,'mcp_fixture',?,'read','succeeded','preview-key',?,1,2)",
            (receipt["turnId"], mid, json.dumps(arguments), result),
        )
        activity_event(
            db, c["id"], "tool.completed", {"toolCallId": "preview"}, turn_id=receipt["turnId"]
        )

    await store.call(record, write=True)
    snapshot = await conversations.messages("alice", c["id"])
    replay = await conversations.events("alice", c["id"])
    preview = replay[-1]["payload"]["activity"]["preview"]
    assert preview == snapshot["activities"][0]["preview"]
    assert "private-input" not in json.dumps(preview) and "private-output" not in json.dumps(
        preview
    )
    assert len(preview["input"]["text"]) == 2000 and preview["input"]["truncated"]
    assert len(preview["output"]["text"]) == 4000 and preview["output"]["truncated"]
    with pytest.raises(DomainError):
        await conversations.events("bob", c["id"])


@pytest.mark.parametrize("legacy", [False, True])
async def test_declined_delegation_never_replays_as_queued(store, legacy):
    from roami_agent.conversation.activity_events import activity_event
    from roami_agent.conversation.transcript import Conversations
    from roami_agent.storage.transcript_repository import message

    conversations = Conversations(store)
    c = await conversations.create("alice")
    receipt = await conversations.accept("alice", c["id"], "delegate", "Create report")

    def record(db):
        mid = message(
            db, c["id"], c["active_branch_id"], "assistant", {"text": ""}, turn_id=receipt["turnId"]
        )
        db.execute(
            "INSERT INTO tool_calls(id,turn_id,assistant_message_id,tool_name,arguments_json,effect,state,idempotency_key,created_ms,updated_ms) VALUES('delegate',?,?,'delegate','{}','write','running','delegate-key',1,1)",
            (receipt["turnId"], mid),
        )
        activity_event(
            db, c["id"], "tool.started", {"toolCallId": "delegate"}, turn_id=receipt["turnId"]
        )
        result = message(
            db,
            c["id"],
            c["active_branch_id"],
            "tool",
            {
                "text": json.dumps(
                    {
                        "acceptedOnly": False,
                        "state": "blocked",
                        "code": "TASK_CONTINUATION_REQUIRED",
                    }
                )
            },
            turn_id=receipt["turnId"],
        )
        db.execute(
            "UPDATE tool_calls SET state='succeeded',result_message_id=?,updated_ms=2 WHERE id='delegate'",
            (result,),
        )
        eid = activity_event(
            db, c["id"], "tool.completed", {"toolCallId": "delegate"}, turn_id=receipt["turnId"]
        )
        if legacy:
            db.execute(
                "UPDATE events SET payload_json=json_set(payload_json,'$.activity.state','succeeded','$.activity.errorCode',NULL) WHERE id=?",
                (eid,),
            )
        return eid

    eid = await store.call(record, write=True)
    snapshot = await conversations.messages("alice", c["id"])
    assert snapshot["activities"][0]["state"] == "blocked"
    assert snapshot["activities"][0]["errorCode"] == "TASK_CONTINUATION_REQUIRED"
    events = await conversations.events("alice", c["id"])
    assert (
        next(e for e in events if e["kind"] == "tool.started")["payload"]["activity"]["state"]
        == "running"
    )
    completed = next(e for e in events if e["id"] == eid)["payload"]["activity"]
    assert (
        completed["state"] == "blocked" and completed["errorCode"] == "TASK_CONTINUATION_REQUIRED"
    )
    stored = await store.call(
        lambda db: row(db, "SELECT payload_json FROM events WHERE id=?", (eid,))
    )
    assert json.loads(stored["payload_json"])["activity"]["state"] == (
        "succeeded" if legacy else "blocked"
    )
    assert (
        await store.call(lambda db: row(db, "SELECT state FROM tool_calls WHERE id='delegate'"))
    )["state"] == "succeeded"
