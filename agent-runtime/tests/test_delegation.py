import json

import pytest

from roami_agent.conversation import Conversations, history, message
from roami_agent.storage import DomainError, row
from roami_agent.tasks import Tasks


async def origin(store):
    conversations = Conversations(store)
    c = await conversations.create("alice")
    receipt = await conversations.accept("alice", c["id"], "one", "Delegate a research task")
    return conversations, c, receipt


async def test_delegate_creates_separate_native_branch_and_idempotent_launch(store):
    conversations, c, _ = await origin(store)
    tasks = Tasks(store, conversations)
    task = await tasks.create("alice", c["id"], "Research memory", key="delegate-1")
    retry = await tasks.create("alice", c["id"], "Research memory", key="delegate-1")
    assert task["id"] == retry["id"]
    run = await store.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    child = await store.call(
        lambda db: row(db, "SELECT * FROM branches WHERE id=?", (run["native_branch_id"],))
    )
    assert child["conversation_id"] != c["id"]
    assert child["parent_branch_id"] is None
    assert len((await conversations.messages("alice", c["id"]))["messages"]) == 1
    with pytest.raises(DomainError, match="TASK_KEY_CONFLICT"):
        await tasks.create("alice", c["id"], "Different task", key="delegate-1")


async def test_task_fork_inherits_only_completed_checkpoint(store):
    conversations, c, receipt = await origin(store)
    tasks = Tasks(store, conversations)

    def finish(db):
        mid = message(
            db,
            c["id"],
            c["active_branch_id"],
            "assistant",
            {"text": "A confirmed decision"},
            turn_id=receipt["turnId"],
        )
        db.execute("UPDATE turns SET state='completed' WHERE id=?", (receipt["turnId"],))
        return mid

    checkpoint = await store.call(finish, write=True)
    await conversations.accept("alice", c["id"], "two", "New requirement after checkpoint")
    task = await tasks.create(
        "alice", c["id"], "Forked task", key="fork-1", from_message_id=checkpoint
    )
    run = await store.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    transcript = await store.call(lambda db: history(db, run["native_branch_id"]))
    assert [json.loads(m["content_json"])["text"] for m in transcript] == [
        "Delegate a research task",
        "A confirmed decision",
        "Forked task",
    ]


async def test_revision_bound_reports_verify_before_success_and_conflict(store):
    conversations, c, _ = await origin(store)
    tasks = Tasks(store, conversations)
    task = await tasks.create("alice", c["id"], "Research", key="one", executor="codex")
    run = await store.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    result = {"state": "succeeded", "summary": "Found docs", "checks": []}
    report = await tasks.report("alice", task["id"], run["id"], 1, result)
    assert report["state"] == "verifying"
    await tasks.report("alice", task["id"], run["id"], 1, result)
    assert (
        await store.call(
            lambda db: db.execute("SELECT COUNT(*) FROM jobs WHERE kind='task.verify'").fetchone()[
                0
            ]
        )
        == 1
    )
    with pytest.raises(DomainError, match="TASK_RESULT_CONFLICT"):
        await tasks.report("alice", task["id"], run["id"], 1, {"state": "failed"})
    with pytest.raises(DomainError, match="TASK_RUN_NOT_FOUND"):
        await tasks.report("bob", task["id"], run["id"], 1, result)


async def test_cancel_parent_marks_entire_child_tree_without_claiming_stopped(store):
    conversations, c, _ = await origin(store)
    tasks = Tasks(store, conversations, max_depth=1)
    parent = await tasks.create("alice", c["id"], "Parent", key="parent")
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='running' WHERE id=?", (parent["id"],)),
        write=True,
    )
    child = await tasks.create("alice", c["id"], "Child", key="child", parent_task_id=parent["id"])
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='running' WHERE id=?", (child["id"],)),
        write=True,
    )
    with pytest.raises(DomainError, match="TASK_DEPTH_EXCEEDED"):
        await tasks.create(
            "alice", c["id"], "Too deep", key="grandchild", parent_task_id=child["id"]
        )
    await tasks.cancel("alice", parent["id"])
    assert {t["state"] for t in await tasks.list("alice")} == {"cancelling"}


async def test_child_coding_task_inherits_parent_deadline(store):
    from roami_agent.storage import encoded, now_ms

    conversations, c, _ = await origin(store)
    tasks = Tasks(store, conversations)
    parent = await tasks.create("alice", c["id"], "Parent", key="parent-deadline")
    deadline = now_ms() + 10_000
    budget = json.loads(parent["budget_json"])
    budget["deadlineMs"] = deadline
    await store.call(
        lambda db: db.execute(
            "UPDATE tasks SET state='running',budget_json=? WHERE id=?",
            (encoded(budget), parent["id"]),
        ),
        write=True,
    )
    child = await tasks.create(
        "alice",
        c["id"],
        "Coding child",
        key="child-deadline",
        executor="codex",
        parent_task_id=parent["id"],
    )
    assert json.loads(child["budget_json"])["deadlineMs"] == deadline
