import json
import re

import pytest

from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.tasks import Tasks
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.native_sessions import NativeSessions
from roami_agent.storage.transcript_repository import message


async def native(store):
    conversations = Conversations(store)
    main = await conversations.create("alice")
    await conversations.accept("alice", main["id"], "request", "Research")
    task = await Tasks(store, conversations).create("alice", main["id"], "Research", key="native")
    session = await store.call(
        lambda db: row(db, "SELECT * FROM native_sessions WHERE task_id=?", (task["id"],))
    )
    return NativeSessions(store), session, main, task


async def test_native_identity_is_separate_from_main_and_idempotent(store):
    service, session, main, task = await native(store)
    assert re.fullmatch(r"\d{8}T\d{9}Z-[a-f0-9]{12}", session["id"])
    assert session["conversation_id"] != main["id"]
    assert session["root_conversation_id"] == main["id"]
    assert session["parent_session_id"] is None
    again = await Tasks(store, Conversations(store)).create(
        "alice", main["id"], "Research", key="native"
    )
    assert again["id"] == task["id"]
    await service.flush()
    directory = service.root / session["id"]
    records = [json.loads(line) for line in (directory / ".chat.jsonl").read_text().splitlines()]
    assert [r["type"] for r in records] == ["session.created", "message.committed"]
    assert records[-1]["payload"]["content"]["text"] == "Research"
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory / ".chat.jsonl").stat().st_mode & 0o777 == 0o600
    assert (
        await store.call(
            lambda db: db.execute(
                "SELECT count(*) FROM native_session_events WHERE payload_json IS NOT NULL"
            ).fetchone()[0]
        )
        == 0
    )
    with pytest.raises(DomainError, match="NATIVE_SESSION_NOT_FOUND"):
        await service.get("bob", session["id"])


async def test_append_retry_and_partial_tail_do_not_duplicate_events(store):
    service, session, _, _ = await native(store)
    entries = await store.call(
        lambda db: [dict(x) for x in db.execute("SELECT * FROM native_session_events ORDER BY seq")]
    )
    metadata = await service.get("alice", session["id"])
    service.files.append(session["id"], [service._record(e) for e in entries], metadata)
    path = service.root / session["id"] / ".chat.jsonl"
    with path.open("ab") as stream:
        stream.write(b'{"seq":')
    await service.flush()
    assert len(path.read_text().splitlines()) == 2
    assert (await service.get("alice", session["id"]))["projectedSeq"] == 2


async def test_gzip_archives_preserve_full_history_and_new_messages(store):
    service, session, _, _ = await native(store)
    await service.flush()
    before = (await service.events("alice", session["id"]))["items"]
    segment = await service.archive("alice", session["id"])
    assert segment["filename"].endswith(".jsonl.gz")
    assert (await service.events("alice", session["id"]))["items"] == before
    await store.call(
        lambda db: message(
            db,
            session["conversation_id"],
            session["branch_id"],
            "user",
            {"text": "Continue original session"},
        ),
        write=True,
    )
    await service.flush()
    records = (await service.events("alice", session["id"]))["items"]
    assert [r["seq"] for r in records] == [1, 2, 3]
    assert records[-1]["payload"]["content"]["text"] == "Continue original session"
    await service.archive("alice", session["id"])
    assert (await service.events("alice", session["id"]))["items"] == records


async def test_transaction_rollback_and_disk_failure_keep_replayable_outbox(store, monkeypatch):
    service, session, _, _ = await native(store)
    await service.flush()

    def rollback(db):
        message(
            db,
            session["conversation_id"],
            session["branch_id"],
            "assistant",
            {"text": "rolled back"},
        )
        raise ValueError("rollback")

    with pytest.raises(ValueError):
        await store.call(rollback, write=True)
    assert (await service.get("alice", session["id"]))["committedSeq"] == 2
    await store.call(
        lambda db: message(
            db, session["conversation_id"], session["branch_id"], "assistant", {"text": "durable"}
        ),
        write=True,
    )
    original = service.files.append

    def full(*args):
        raise OSError("disk full")

    monkeypatch.setattr(service.files, "append", full)
    await service.flush()
    assert (await service.get("alice", session["id"]))[
        "archiveError"
    ] == "NATIVE_JOURNAL_UNAVAILABLE"
    assert await store.call(
        lambda db: row(db, "SELECT payload_json FROM native_session_events WHERE seq=3")
    )
    monkeypatch.setattr(service.files, "append", original)
    await service.flush()
    assert (await service.events("alice", session["id"]))["items"][-1]["payload"]["content"][
        "text"
    ] == "durable"


async def test_cold_payloads_restore_original_context_across_restart(store):
    from roami_agent.storage.database import Database
    from roami_agent.storage.transcript_repository import history

    service, session, _, _ = await native(store)
    old = "old public evidence " * 1000
    mid = await store.call(
        lambda db: message(
            db, session["conversation_id"], session["branch_id"], "assistant", {"text": old}
        ),
        write=True,
    )
    await store.call(
        lambda db: db.execute("UPDATE messages SET created_ms=1 WHERE id=?", (mid,)), write=True
    )
    segment = await service.archive("alice", session["id"])
    raw = await store.call(
        lambda db: db.execute("SELECT content_json FROM messages WHERE id=?", (mid,)).fetchone()[0]
    )
    assert "_nativePayload" in raw and old not in raw
    assert segment["compressedBytes"] < segment["rawBytes"]
    assert (
        await store.call(lambda db: row(db, "SELECT content_json FROM messages WHERE id=?", (mid,)))
    )["content_json"] == json.dumps(
        {"text": old}, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    assert (await service.conversation("alice", session["id"]))["messages"][-1]["content"][
        "text"
    ] == old
    await store.close()
    reopened = Database(store.path, store.data_root, managed=False)
    await reopened.open()
    try:
        history_text = await reopened.call(lambda db: history(db, session["branch_id"]))
        assert json.loads(history_text[-1]["content_json"])["text"] == old
        text = await reopened.call(
            lambda db: db.execute(
                "SELECT json_extract(native_content(content_json),'$.text') FROM messages WHERE id=?",
                (mid,),
            ).fetchone()[0]
        )
        assert text == old
        service.files.root.joinpath(session["id"], segment["filename"]).unlink()
        reopened.connection.native_payloads.cache.clear()
        with pytest.raises(DomainError, match="NATIVE_PAYLOAD_UNAVAILABLE"):
            await reopened.call(
                lambda db: row(db, "SELECT content_json FROM messages WHERE id=?", (mid,))
            )
    finally:
        await reopened.close()


async def test_private_reasoning_credentials_and_deleted_messages_are_not_exported(store):
    service, session, _, _ = await native(store)
    mid = await store.call(
        lambda db: message(
            db,
            session["conversation_id"],
            session["branch_id"],
            "assistant",
            {
                "text": "Public result",
                "reasoning": "private reasoning",
                "authorization": "Bearer a-secret-token",
            },
        ),
        write=True,
    )
    await service.flush()
    record = (await service.events("alice", session["id"]))["items"][-1]
    assert "private reasoning" not in json.dumps(record) and "a-secret-token" not in json.dumps(
        record
    )
    await store.call(
        lambda db: db.execute(
            "UPDATE messages SET deleted_ms=1,status='deleted' WHERE id=?", (mid,)
        ),
        write=True,
    )
    values = (await service.events("alice", session["id"]))["items"]
    assert not any(item["entityId"] == mid for item in values)


async def test_archive_corruption_and_symlink_fail_closed(store):
    service, session, _, _ = await native(store)
    segment = await service.archive("alice", session["id"])
    path = service.root / session["id"] / segment["filename"]
    path.write_bytes(b"damaged gzip")
    with pytest.raises(DomainError, match="NATIVE_ARCHIVE_CORRUPT"):
        await service.events("alice", session["id"])


async def test_completed_native_continues_same_branch_then_user_closes(store):
    from test_runtime import ConversationModel, until

    from roami_agent.app import Runtime

    runtime = Runtime(store, ConversationModel())
    try:
        main = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", main["id"], "整理访谈行动项", key="first", record_intent=True
        )
        await runtime.start()
        await until(
            store,
            lambda db: row(
                db,
                "SELECT id FROM tasks WHERE id=? AND state IN ('succeeded','waiting_user')",
                (task["id"],),
            ),
        )
        detail = await runtime.tasks.get("alice", task["id"])
        native_id = detail["task"]["nativeSession"]["id"]
        first = await runtime.native_sessions.get("alice", native_id)
        with pytest.raises(DomainError, match="NATIVE_SESSION_USE_TASK_CHANNEL"):
            await runtime.chat.submit("alice", first["conversationId"], "wrong", "继续")
        await runtime.tasks.revisions.request("alice", task["id"], "加上负责人", 1, "continue")
        runtime.wakeup.set()
        await until(
            store,
            lambda db: row(
                db,
                "SELECT id FROM tasks WHERE id=? AND revision=2 AND state IN ('succeeded','waiting_user')",
                (task["id"],),
            ),
        )
        current = await runtime.tasks.get("alice", task["id"])
        assert current["task"]["nativeSession"]["id"] == native_id
        assert (await runtime.native_sessions.get("alice", native_id))["branchId"] == first[
            "branchId"
        ]
        assert (await runtime.native_sessions.conversation("alice", native_id))["messages"][-1][
            "role"
        ] == "assistant"
        await runtime.task_sessions.close("alice", task["id"], 2, current["attempts"][0]["id"])
        assert (await runtime.tasks.get("alice", task["id"]))["sessionClosure"]["state"] == "closed"
        assert (await runtime.conversations.get("alice", main["id"]))["id"] == main["id"]
        with pytest.raises(DomainError, match="TASK_SESSION_CLOSED"):
            await runtime.tasks.revisions.request("alice", task["id"], "再继续", 2, "closed")
    finally:
        await runtime.close()


async def test_child_sessions_keep_flat_directories_and_parent_identity(store):
    service, parent, main, task = await native(store)
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='running' WHERE id=?", (task["id"],)),
        write=True,
    )
    child = await Tasks(store, Conversations(store)).create(
        "alice",
        parent["conversation_id"],
        "Check one source",
        key="child",
        parent_task_id=task["id"],
    )
    child_session = await store.call(
        lambda db: row(db, "SELECT * FROM native_sessions WHERE task_id=?", (child["id"],))
    )
    assert child_session["id"] != parent["id"]
    assert child_session["parent_session_id"] == parent["id"]
    assert child_session["parent_conversation_id"] == parent["conversation_id"]
    assert child_session["root_conversation_id"] == main["id"]
    await service.flush()
    assert (service.root / child_session["id"] / ".chat.jsonl").is_file()
    assert not (service.root / parent["id"] / child_session["id"]).exists()


async def test_native_http_history_is_owned_and_paged_without_creating_work(store):
    import httpx
    from test_runtime import ConversationModel

    from roami_agent.app import Runtime
    from roami_agent.server.http import create_app

    runtime = Runtime(store, ConversationModel())
    _service, session, _, _ = await native(store)
    for index in range(5):
        await store.call(
            lambda db, index=index: message(
                db,
                session["conversation_id"],
                session["branch_id"],
                "assistant",
                {"text": str(index)},
            ),
            write=True,
        )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
            base_url="http://test",
        ) as client:
            response = await client.get(
                "/v1/native-sessions/" + session["id"] + "/conversation?limit=2",
                headers={"X-Roami-Owner": "alice"},
            )
            assert response.status_code == 200
            page = response.json()["data"]
            assert [m["content"]["text"] for m in page["messages"]] == ["3", "4"]
            older = await client.get(
                "/v1/native-sessions/"
                + session["id"]
                + "/conversation?limit=2&before="
                + str(page["before"]),
                headers={"X-Roami-Owner": "alice"},
            )
            assert [m["content"]["text"] for m in older.json()["data"]["messages"]] == ["1", "2"]
            foreign = await client.get(
                "/v1/native-sessions/" + session["id"] + "/conversation",
                headers={"X-Roami-Owner": "bob"},
            )
            assert foreign.status_code == 404
            invalid = await client.get(
                "/v1/native-sessions/" + session["id"] + "/events?after=-1",
                headers={"X-Roami-Owner": "alice"},
            )
            assert invalid.status_code == 422
            assert (
                await store.call(lambda db: db.execute("SELECT count(*) FROM tasks").fetchone()[0])
                == 1
            )
    finally:
        await runtime.close()


async def test_short_old_messages_stay_inline_when_a_reference_would_be_larger(store):
    service, session, _, _ = await native(store)
    mid = await store.call(
        lambda db: message(
            db, session["conversation_id"], session["branch_id"], "assistant", {"text": "Done"}
        ),
        write=True,
    )
    await store.call(
        lambda db: db.execute("UPDATE messages SET created_ms=1 WHERE id=?", (mid,)), write=True
    )
    await service.archive("alice", session["id"])
    raw = await store.call(
        lambda db: db.execute("SELECT content_json FROM messages WHERE id=?", (mid,)).fetchone()[0]
    )
    assert json.loads(raw) == {"text": "Done"}


@pytest.mark.parametrize("pending", ["tool", "steering", "professional_outcome"])
async def test_closing_parent_checks_pending_work_in_descendants(store, pending):
    from roami_agent.dispatch.task_sessions import TaskSessions
    from roami_agent.protocol.identity import identity

    service, parent, _, task = await native(store)
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='running' WHERE id=?", (task["id"],)),
        write=True,
    )
    child = await Tasks(store, Conversations(store)).create(
        "alice",
        parent["conversation_id"],
        "Child work",
        key="close-child",
        parent_task_id=task["id"],
        executor="codex" if pending == "professional_outcome" else "native",
        target={"kind": "new_session", "directory": str(store.data_root)},
    )

    def prepare(db):
        for ident in (task["id"], child["id"]):
            db.execute("UPDATE tasks SET state='failed' WHERE id=?", (ident,))
            db.execute(
                "UPDATE task_attempts SET state='failed',finished_ms=1 WHERE task_id=?", (ident,)
            )
        child_run = row(db, "SELECT * FROM task_attempts WHERE task_id=?", (child["id"],))
        if pending == "tool":
            native_child = row(db, "SELECT * FROM native_sessions WHERE task_id=?", (child["id"],))
            turn = identity()
            db.execute(
                "INSERT INTO turns(id,conversation_id,branch_id,trigger_kind,state,created_ms) VALUES(?,?,?,'continuation','completed',1)",
                (turn, native_child["conversation_id"], native_child["branch_id"]),
            )
            mid = message(
                db,
                native_child["conversation_id"],
                native_child["branch_id"],
                "assistant",
                {"text": "Uncertain write"},
                turn_id=turn,
            )
            call = identity()
            db.execute(
                "INSERT INTO tool_calls(id,turn_id,assistant_message_id,tool_name,arguments_json,effect,state,idempotency_key,created_ms,updated_ms) VALUES(?,?,?,'write_file','{}','write','unknown',?,1,1)",
                (call, turn, mid, call),
            )
        elif pending == "professional_outcome":
            db.execute(
                "UPDATE task_attempts SET state='unknown',result_json=? WHERE id=?",
                (json.dumps({"inputStopped": False, "outcomeKnown": False}), child_run["id"]),
            )
        return row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))

    run = await store.call(prepare, write=True)
    if pending == "steering":
        await Tasks(store, Conversations(store)).revisions.request(
            "alice", child["id"], "Continue this child", 1, "pending-child"
        )

    async def confirm(*args, **kwargs):
        raise AssertionError("Unsettled parent must not be confirmed")

    closer = TaskSessions(store, None, confirm)
    expected = {
        "tool": "TASK_SESSION_BUSY",
        "steering": "TASK_STEER_PENDING",
        "professional_outcome": "TASK_OUTCOME_UNRESOLVED",
    }[pending]
    with pytest.raises(DomainError, match=expected):
        await closer.close("alice", task["id"], 1, run["id"])
    assert (
        await store.call(
            lambda db: row(db, "SELECT * FROM task_session_closures WHERE task_id=?", (task["id"],))
        )
        is None
    )
    assert (await service.get("alice", parent["id"]))["lifecycle"] == "open"


async def test_native_close_database_failure_rolls_back_the_input_fence(store, monkeypatch):
    from roami_agent.dispatch import task_sessions

    service, session, _, task = await native(store)

    def complete(db):
        db.execute("UPDATE tasks SET state='failed' WHERE id=?", (task["id"],))
        db.execute(
            "UPDATE task_attempts SET state='failed',finished_ms=1 WHERE task_id=?", (task["id"],)
        )
        return row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))

    run = await store.call(complete, write=True)

    async def confirm(*args, **kwargs):
        raise AssertionError("Failed execution must not become verified success")

    original = task_sessions.event

    def fail_event(*args, **kwargs):
        raise DomainError("INJECTED_DATABASE_FAILURE", 503)

    monkeypatch.setattr(task_sessions, "event", fail_event)
    closer = task_sessions.TaskSessions(store, None, confirm)
    with pytest.raises(DomainError, match="INJECTED_DATABASE_FAILURE"):
        await closer.close("alice", task["id"], 1, run["id"])
    assert (
        await store.call(
            lambda db: row(db, "SELECT * FROM task_session_closures WHERE task_id=?", (task["id"],))
        )
        is None
    )
    assert (await service.get("alice", session["id"]))["lifecycle"] == "open"
    monkeypatch.setattr(task_sessions, "event", original)
    assert (await closer.close("alice", task["id"], 1, run["id"]))["state"] == "closed"
    assert (
        await store.call(lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],)))
    )["state"] == "failed"


async def test_native_conversation_interleaves_tool_results_and_redacts_payloads(store):
    service, session, _, _ = await native(store)

    def prepare(db):
        turn = "native-inline-turn"
        db.execute(
            "INSERT INTO turns(id,conversation_id,branch_id,trigger_kind,state,created_ms) "
            "VALUES(?,?,?,'continuation','completed',1)",
            (turn, session["conversation_id"], session["branch_id"]),
        )
        call = {
            "id": "provider-call",
            "function": {
                "name": "bash",
                "arguments": json.dumps({"command": "node build.mjs", "authorization": "hdr-123"}),
            },
        }
        assistant = message(
            db,
            session["conversation_id"],
            session["branch_id"],
            "assistant",
            {"text": "First I will build the report.", "tool_calls": [call]},
            turn_id=turn,
        )
        result = message(
            db,
            session["conversation_id"],
            session["branch_id"],
            "tool",
            {
                "tool_call_id": "provider-call",
                "text": json.dumps({"stdout": "Build passed", "password": "pwd-123"}),
            },
            turn_id=turn,
        )
        db.execute(
            "INSERT INTO tool_calls(id,turn_id,assistant_message_id,result_message_id,tool_name,"
            "arguments_json,effect,state,idempotency_key,created_ms,updated_ms) "
            "VALUES(?,?,?,?,'bash','{}','write','succeeded',?,1,1)",
            ("native-inline-call", turn, assistant, result, turn + ":provider-call"),
        )
        message(
            db,
            session["conversation_id"],
            session["branch_id"],
            "assistant",
            {"text": "The report is ready."},
            turn_id=turn,
        )

    await store.call(prepare, write=True)
    transcript = await service.conversation("alice", session["id"])
    messages = transcript["messages"]
    assert [item["role"] for item in messages] == ["user", "assistant", "tool", "assistant"]
    assert messages[1]["content"]["text"] == "First I will build the report."
    assert messages[2]["content"]["toolState"] == "succeeded"
    assert messages[2]["content"]["tool_call_id"] == "provider-call"
    assert "Build passed" in messages[2]["content"]["text"]
    assert "hdr-123" not in json.dumps(transcript)
    assert "pwd-123" not in json.dumps(transcript)
    assert "[redacted]" in messages[1]["content"]["tool_calls"][0]["function"]["arguments"]
    tail = await service.conversation("alice", session["id"], limit=2)
    assert [item["role"] for item in tail["messages"]] == ["tool", "assistant"]
    earlier = await service.conversation("alice", session["id"], before=tail["before"], limit=2)
    assert earlier["messages"][-1]["content"]["tool_calls"][0]["id"] == "provider-call"
    await service.archive("alice", session["id"])
    assert (await service.conversation("alice", session["id"]))["messages"] == messages
    with pytest.raises(DomainError, match="NATIVE_SESSION_NOT_FOUND"):
        await service.conversation("bob", session["id"])
