"""A repeated user request must not hide an older unresolved task behind recent work."""

import json

import pytest
from test_navigation_recovery import interrupted_navigation
from test_swarm_main_verification import wire

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.task_context import recent_task_context
from roami_agent.storage.task_continuation import unresolved_repeated_requests


async def invoke(runtime, turn, binding, name, args):
    mid = await runtime.journal.start(turn)
    call = wire(name, args)
    bound = dict(binding, toolCallId=call["id"], assistantMessageId=mid)
    return await runtime.gateway.invoke(turn, mid, call, "main", bound)


async def repeat_turn(runtime, task, text="Check pricing"):
    for index in range(4):
        await runtime.tasks.create(
            "alice",
            task["origin_conversation_id"],
            f"Other work {index}",
            key=f"unrelated-{index}",
            record_intent=True,
        )
    await runtime.db.call(
        lambda db: db.execute("UPDATE tasks SET created_ms=1 WHERE id=?", (task["id"],)),
        write=True,
    )
    source = await runtime.conversations.accept(
        "alice", task["origin_conversation_id"], "repeat-request", text
    )
    job = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM jobs WHERE aggregate_id=?", (source["turnId"],))
    )
    turn = await runtime.mailbox.claim(job)
    return turn, {
        "owner": "alice",
        "conversation": task["origin_conversation_id"],
        "turnId": turn["id"],
        "originMessageId": source["messageId"],
    }


@pytest.mark.parametrize("write_unknown", [False, True])
async def test_repeated_request_keeps_old_identity_and_blocks_replacement(store, write_unknown):
    runtime, task = await interrupted_navigation(store)
    try:
        if write_unknown:
            await store.call(
                lambda db: db.execute(
                    "UPDATE resource_actions SET action_json=json_set(action_json,'$.verb','click') WHERE task_id=?",
                    (task["id"],),
                ),
                write=True,
            )
        prior = (await runtime.tasks.get("alice", task["id"]))["attempts"][0]
        turn, binding = await repeat_turn(runtime, task)
        context = await store.call(lambda db: recent_task_context(db, turn))
        assert task["id"] in {item["taskId"] for item in context}
        assert next(item for item in context if item["taskId"] == task["id"])["unresolved"] is True
        before = await store.call(lambda db: db.execute("SELECT count(*) FROM tasks").fetchone()[0])
        result = await invoke(
            runtime,
            turn,
            binding,
            "delegate",
            {"goal": "Fresh source lookup with different assistant wording", "executor": "native"},
        )
        assert result["code"] == "TASK_FAILURE_REVIEW_REQUIRED" and result["acceptedOnly"] is False
        assert any(item["taskId"] == task["id"] for item in result["tasks"])
        assert before == await store.call(
            lambda db: db.execute("SELECT count(*) FROM tasks").fetchone()[0]
        )
        if write_unknown:
            with pytest.raises(DomainError, match="TASK_OUTCOME_UNRESOLVED"):
                await runtime.tasks.revisions.request(
                    "alice",
                    task["id"],
                    "Check pricing",
                    1,
                    "continue",
                    source_turn_id=turn["id"],
                    source_conversation_id=binding["conversation"],
                )
        else:
            await runtime.tasks.revisions.request(
                "alice",
                task["id"],
                "Check pricing",
                1,
                "continue",
                source_turn_id=turn["id"],
                source_conversation_id=binding["conversation"],
            )
            await runtime.tasks.revisions.advance()
            assert (await runtime.tasks.get("alice", task["id"]))["task"]["revision"] == 2
        old = await store.call(
            lambda db: row(
                db, "SELECT state,result_json FROM task_attempts WHERE id=?", (prior["id"],)
            )
        )
        assert old["state"] == "unknown" and json.loads(old["result_json"]) == prior["result"]
    finally:
        await runtime.close()


@pytest.mark.parametrize("text", ["Start an independent pricing task", "Check another topic"])
async def test_different_explicit_requests_can_create_new_work(store, text):
    runtime, task = await interrupted_navigation(store)
    try:
        turn, binding = await repeat_turn(runtime, task, text)
        result = await invoke(
            runtime, turn, binding, "delegate", {"goal": text, "executor": "native"}
        )
        assert result["acceptedOnly"] is True and result["taskId"] != task["id"]
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "excluded", ["branch", "owner", "forgotten", "deleted", "future", "settled"]
)
async def test_repeat_candidates_respect_scope_and_latest_outcome(store, excluded):
    runtime, task = await interrupted_navigation(store)
    try:
        turn, binding = await repeat_turn(runtime, task)

        other = await runtime.conversations.create("alice")

        def change(db):
            if excluded == "branch":
                db.execute(
                    "UPDATE tasks SET origin_branch_id=? WHERE id=?",
                    (other["active_branch_id"], task["id"]),
                )
            elif excluded == "owner":
                db.execute("UPDATE tasks SET owner_id='another-owner' WHERE id=?", (task["id"],))
            elif excluded == "forgotten":
                db.execute(
                    "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'forgotten_memory_source',1)",
                    (task["origin_message_id"],),
                )
            elif excluded == "deleted":
                db.execute(
                    "UPDATE messages SET deleted_ms=1 WHERE id=?", (task["origin_message_id"],)
                )
            elif excluded == "future":
                db.execute(
                    "UPDATE tasks SET created_ms=? WHERE id=?", (turn["created_ms"] + 1, task["id"])
                )
            else:
                old = row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
                db.execute(
                    "UPDATE tasks SET revision=2,state='succeeded' WHERE id=?", (task["id"],)
                )
                fields = dict(
                    old,
                    id="settled-attempt",
                    task_revision=2,
                    attempt_no=2,
                    launch_id="settled-launch",
                    state="succeeded",
                    result_json='{"outcomeKnown":true,"inputStopped":true}',
                )
                db.execute(
                    "INSERT INTO task_attempts("
                    + ",".join(fields)
                    + ") VALUES("
                    + ",".join("?" for _ in fields)
                    + ")",
                    tuple(fields.values()),
                )
            origin = row(db, "SELECT * FROM messages WHERE id=?", (binding["originMessageId"],))
            return unresolved_repeated_requests(db, turn, origin)

        assert await store.call(change, write=True) == []
        context = await store.call(lambda db: recent_task_context(db, turn))
        assert task["id"] not in {item["taskId"] for item in context}
        result = await invoke(
            runtime, turn, binding, "delegate", {"goal": "Check pricing", "executor": "native"}
        )
        assert result["acceptedOnly"] is True
    finally:
        await runtime.close()
