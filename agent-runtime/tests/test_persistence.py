import asyncio
import fcntl
import json
import os

import pytest

from roami_agent.conversation.transcript import Conversations
from roami_agent.memory.records import Memories
from roami_agent.protocol.errors import DomainError
from roami_agent.replies.notifications import Notifications
from roami_agent.storage.database import Database, row
from roami_agent.storage.transcript_repository import message


async def test_intake_retry_conflict_owner_and_restart(store):
    conversations = Conversations(store)
    first = await conversations.create("alice", "Main")
    receipt = await conversations.accept("alice", first["id"], "request-1", "remember this")
    again = await conversations.accept("alice", first["id"], "request-1", "remember this")
    assert again["turnId"] == receipt["turnId"]
    assert again["messageId"] == receipt["messageId"]
    assert again["cursor"] == receipt["cursor"]
    with pytest.raises(DomainError, match="REQUEST_KEY_CONFLICT"):
        await conversations.accept("alice", first["id"], "request-1", "different")
    with pytest.raises(DomainError, match="CONVERSATION_NOT_FOUND"):
        await conversations.messages("bob", first["id"])
    assert len((await conversations.messages("alice", first["id"]))["messages"]) == 1
    await store.close()
    reopened = Database(store.path, store.data_root, managed=False)
    await reopened.open()
    try:
        assert len((await Conversations(reopened).messages("alice", first["id"]))["messages"]) == 1
    finally:
        await reopened.close()


async def test_maintenance_lock_and_single_writer_instance(store):
    handle = os.open(store.data_root / "locks/storage.lock", os.O_RDWR)
    try:
        with pytest.raises(BlockingIOError):
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(handle)
    second = Database(store.path, store.data_root, managed=False)
    with pytest.raises(DomainError, match="STORAGE_BUSY"):
        await second.open()
    assert store.path.exists()


async def test_commit_survives_cancelled_caller_and_atomic_rollback(store):
    started = asyncio.Event()
    loop = asyncio.get_running_loop()

    def write(db):
        loop.call_soon_threadsafe(started.set)
        import time

        time.sleep(0.03)
        db.execute("INSERT INTO owner_versions(owner_id) VALUES('durable')")

    task = asyncio.create_task(store.call(write, write=True))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (
        await store.call(lambda db: db.execute("SELECT COUNT(*) FROM owner_versions").fetchone()[0])
        == 1
    )

    def fails(db):
        db.execute("INSERT INTO owner_versions(owner_id) VALUES('rolled-back')")
        raise RuntimeError("rollback")

    with pytest.raises(RuntimeError):
        await store.call(fails, write=True)
    assert (
        await store.call(lambda db: db.execute("SELECT COUNT(*) FROM owner_versions").fetchone()[0])
        == 1
    )


async def test_fork_completed_round_preserves_parent(store):
    conversations = Conversations(store)
    c = await conversations.create("alice")
    receipt = await conversations.accept("alice", c["id"], "one", "question")

    def finish(db):
        mid = message(
            db,
            c["id"],
            c["active_branch_id"],
            "assistant",
            {"text": "answer"},
            turn_id=receipt["turnId"],
        )
        db.execute("UPDATE turns SET state='completed' WHERE id=?", (receipt["turnId"],))
        return mid

    mid = await store.call(finish, write=True)
    branch = await conversations.fork("alice", c["id"], mid)
    assert branch["branchId"] != c["active_branch_id"]
    await conversations.accept("alice", c["id"], "two", "branch-only")
    result = await conversations.messages("alice", c["id"])
    assert [m["content"]["text"] for m in result["messages"]] == [
        "question",
        "answer",
        "branch-only",
    ]
    assert (
        await store.call(
            lambda db: db.execute(
                "SELECT COUNT(*) FROM messages WHERE branch_id=?", (c["active_branch_id"],)
            ).fetchone()[0]
        )
        == 2
    )


async def test_recovery_marks_partial_and_unknown_tools(store):
    conversations = Conversations(store)
    c = await conversations.create("alice")
    receipt = await conversations.accept("alice", c["id"], "one", "question")

    def partial(db):
        db.execute("UPDATE turns SET state='running' WHERE id=?", (receipt["turnId"],))
        return message(
            db,
            c["id"],
            c["active_branch_id"],
            "assistant",
            {"text": "partial"},
            turn_id=receipt["turnId"],
            status="streaming",
        )

    await store.call(partial, write=True)
    await conversations.recover()
    messages = (await conversations.messages("alice", c["id"]))["messages"]
    assert messages[-1]["status"] == "interrupted"
    assert any(
        e["kind"] == "turn.interrupted" for e in await conversations.events("alice", c["id"])
    )


async def test_cjk_memory_scope_version_and_forgetting(store):
    conversations, memories = Conversations(store), Memories(store)
    c = await conversations.create("alice")
    receipt = await conversations.accept("alice", c["id"], "one", "用 Python 做记忆召回")
    memory = await memories.save(
        "alice",
        "记忆决策",
        "使用 Python 实现记忆召回",
        receipt["messageId"],
        conversation_id=c["id"],
        project_id="project-a",
    )
    assert len(await memories.search("alice", "记忆", project_id="project-a")) == 1
    assert await memories.search("alice", "记忆", project_id="project-b") == []
    assert await memories.search("bob", "记忆") == []
    updated = await memories.save(
        "alice",
        "记忆决策",
        "使用 Python 和 FTS 实现记忆召回",
        receipt["messageId"],
        conversation_id=c["id"],
        project_id="project-a",
    )
    assert updated["revision"] == 2
    assert updated["supersedes_id"] == memory["id"]
    await memories.forget("alice", updated["id"])
    assert await memories.search("alice", "记忆") == []
    with pytest.raises(DomainError, match="MEMORY_FORGOTTEN"):
        await memories.save(
            "alice",
            "记忆决策",
            "使用 Python 和 FTS 实现记忆召回",
            receipt["messageId"],
            conversation_id=c["id"],
            project_id="project-a",
        )


async def test_proactive_delivery_atomic_dedupe_read_watermark(store):
    conversations, notifications = Conversations(store), Notifications(store)
    c = await conversations.create("alice")
    first = await notifications.publish(
        "alice", c["id"], "Task done", source="task", dedupe_key="t1"
    )
    retry = await notifications.publish(
        "alice", c["id"], "Task done", source="task", dedupe_key="t1"
    )
    assert first["eventId"] == retry["eventId"]
    assert await notifications.unread("alice") == 1
    assert await notifications.unread("bob") == 0
    with pytest.raises(DomainError, match="NOTIFICATION_KEY_CONFLICT"):
        await notifications.publish("alice", c["id"], "Changed", source="task", dedupe_key="t1")
    second = await notifications.publish(
        "alice", c["id"], "Need your decision", source="task", dedupe_key="t2"
    )
    await notifications.mark_read("alice", c["id"], first["eventId"])
    assert await notifications.unread("alice") == 1
    await notifications.mark_read("alice", c["id"], second["eventId"])
    await notifications.mark_read("alice", c["id"], first["eventId"])
    assert await notifications.unread("alice") == 0
    assert len((await conversations.messages("alice", c["id"]))["messages"]) == 2


async def test_catalog_required_and_ready_file_cannot_be_recreated(tmp_path):
    root = tmp_path / "database"
    root.mkdir()
    (tmp_path / "storage-layout.json").write_text(
        json.dumps({"instanceId": "one", "paths": {"databaseRoot": str(root)}})
    )
    (root / "catalog.json").write_text(
        json.dumps(
            {
                "instanceId": "one",
                "databases": [
                    {
                        "id": "agent-runtime",
                        "kind": "agent",
                        "owner": "python-agent",
                        "state": "ready",
                        "path": "agents/runtime.db",
                    }
                ],
            }
        )
    )
    db = Database(root / "agents/runtime.db", tmp_path)
    with pytest.raises(DomainError, match="DATABASE_MISSING"):
        await db.open()
    assert not db.path.exists()


async def test_unread_count_is_not_limited_by_inbox_page_and_delivery_is_atomic(store):
    conversations, notifications = Conversations(store), Notifications(store)
    c = await conversations.create("alice")
    await store.call(
        lambda db: db.execute(
            "INSERT INTO channel_bindings(id,conversation_id,channel_kind,route_json,created_ms) VALUES(?,?,'web','{}',1)",
            ("web-channel", c["id"]),
        ),
        write=True,
    )
    for index in range(205):
        await notifications.publish(
            "alice", c["id"], f"Result {index}", source="test", dedupe_key=str(index)
        )
    assert len(await notifications.list("alice")) == 200
    assert await notifications.unread("alice") == 205
    assert (
        await store.call(
            lambda db: db.execute(
                "SELECT COUNT(*) FROM deliveries WHERE state='pending'"
            ).fetchone()[0]
        )
        == 205
    )
    assert await notifications.unread("bob") == 0


async def test_conversation_creation_retry_and_worker_history_scope(store):
    from roami_agent.dispatch.tasks import Tasks

    conversations = Conversations(store)
    first = await conversations.create("alice", request_key="new-chat")
    assert (await conversations.create("alice", request_key="new-chat"))["id"] == first["id"]
    with pytest.raises(DomainError, match="REQUEST_KEY_CONFLICT"):
        await conversations.create("alice", "Different", request_key="new-chat")
    await conversations.accept("alice", first["id"], "first-turn", "A useful conversation title")
    assert (await conversations.list("alice"))[0]["title"] == "A useful conversation title"
    task = await Tasks(store, conversations).create("alice", first["id"], "Child", key="worker")
    child = await store.call(
        lambda db: row(
            db,
            "SELECT b.conversation_id FROM task_attempts a JOIN branches b ON b.id=a.native_branch_id WHERE a.task_id=?",
            (task["id"],),
        )
    )
    assert child["conversation_id"] != first["id"]
    assert [c["id"] for c in await conversations.list("alice")] == [first["id"]]
    notifications = Notifications(store)
    await notifications.publish(
        "alice", child["conversation_id"], "Internal result", source="worker", dedupe_key="result"
    )
    assert await notifications.unread("alice") == 0
    assert await notifications.list("alice") == []
    notice = await notifications.publish(
        "alice", first["id"], "User result", source="main", dedupe_key="result"
    )
    assert await notifications.unread("alice") == 1
    assert (await notifications.list("alice"))[0]["branch_id"] == first["active_branch_id"]
    snapshot = await conversations.messages("alice", first["id"], first["active_branch_id"])
    assert snapshot["messages"][-1]["completedEventId"] == notice["eventId"]
    events = await conversations.events("alice", first["id"])
    assert events[-1]["branchId"] == snapshot["branchId"]
    child_snapshot = await conversations.messages("alice", child["conversation_id"])
    with pytest.raises(DomainError, match="BRANCH_NOT_FOUND"):
        await conversations.messages("alice", first["id"], child_snapshot["branchId"])
