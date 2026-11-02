"""Existing executor conversations receive the user's delta without replay or new permissions."""

import json

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


async def prepare(runtime, store, user, attachment_ids=None):
    conversation = await runtime.conversations.create("alice")
    task = await runtime.tasks.create(
        "alice",
        conversation["id"],
        "Original detailed implementation brief. Do not merge.",
        key="original",
        executor="codex",
        title="修复首屏加载",
        target={"kind": "project", "projectId": "roami"},
        record_intent=True,
    )

    def finish(db):
        db.execute("UPDATE tasks SET state='succeeded' WHERE id=?", (task["id"],))
        db.execute(
            "UPDATE task_attempts SET state='succeeded',session_id='original-session',result_json=? WHERE task_id=?",
            (json.dumps({"state": "succeeded", "summary": "PR ready"}), task["id"]),
        )

    await store.call(finish, write=True)
    source = await runtime.conversations.accept(
        "alice", conversation["id"], "followup", user, attachment_ids
    )
    job = await store.call(
        lambda db: row(db, "SELECT * FROM jobs WHERE aggregate_id=?", (source["turnId"],))
    )
    await runtime.mailbox.claim(job)
    return conversation, task, source


@pytest.mark.parametrize("with_attachment", [False, True])
async def test_merge_followup_delivers_only_user_words_and_keeps_task_title(store, with_attachment):
    runtime = Runtime(store, ConversationModel())
    try:
        attachment = (
            await runtime.attachments.upload(
                "alice", "merge-notes.md", "upload", b"Current input only"
            )
            if with_attachment
            else None
        )
        conversation, task, source = await prepare(
            runtime, store, "代码合入", [attachment["id"]] if attachment else None
        )
        operation = await runtime.tasks.revisions.request(
            "alice",
            task["id"],
            "用户确认合入并发版，打 tag 发布 Release。",
            1,
            "merge",
            source_turn_id=source["turnId"],
            source_conversation_id=conversation["id"],
        )
        assert operation["text"] == "代码合入"
        await runtime.tasks.revisions.advance()
        current = (await runtime.tasks.get("alice", task["id"]))["task"]
        intent = json.loads(current["intent_json"])
        assert intent["continuation"]["text"] == "代码合入"
        assert "Original detailed" in intent["goal"]
        assert "发版" not in intent["goal"] and "Release" not in intent["goal"]
        run = await store.call(
            lambda db: row(
                db, "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=2", (task["id"],)
            )
        )
        await store.call(
            lambda db: db.execute("UPDATE tasks SET state='preparing' WHERE id=?", (task["id"],)),
            write=True,
        )
        executor = CodingExecutor(store, Settings())
        executor.artifacts = runtime.artifacts

        class Capabilities:
            async def brief(self, *args):
                raise AssertionError(
                    "An existing session must not receive the full capabilities preamble again"
                )

        executor.capabilities = Capabilities()
        submitted = []

        async def command(*args, spec=None):
            submitted.append(spec)
            return {"state": "running", "session": "original-session"}

        executor.command = command
        await executor.run(current, run)
        if attachment:
            assert submitted[0]["prompt"].startswith("代码合入\n\nInput files")
            assert "merge-notes.md" in submitted[0]["prompt"]
            assert "Original detailed" not in submitted[0]["prompt"]
            assert "routing" not in submitted[0]["prompt"]
        else:
            assert submitted[0]["prompt"] == "代码合入"
        assert submitted[0]["title"] == "修复首屏加载"
        assert submitted[0]["sessionId"] == "original-session"
        snapshot = await runtime.conversations.messages("alice", conversation["id"])
        messages = snapshot["messages"]
        assert not any(m["content"].get("taskSteer") for m in messages)
        assert (
            sum(m["role"] == "user" and m["content"]["text"] == "代码合入" for m in messages) == 1
        )
        activity = next(item for item in snapshot["activities"] if item.get("taskId") == task["id"])
        assert activity["anchorMessageId"] == source["messageId"]
        audit = await store.call(
            lambda db: row(
                db, "SELECT content_json FROM messages WHERE id=?", (current["origin_message_id"],)
            )
        )
        assert json.loads(audit["content_json"])["text"] == "代码合入"
    finally:
        await runtime.close()


@pytest.mark.parametrize("quote", ["先把代码合入", "虚构的发版授权"])
async def test_mixed_request_passes_only_exact_source_quote_for_existing_task(store, quote):
    runtime = Runtime(store, ConversationModel())
    try:
        conversation, task, source = await prepare(
            runtime, store, "先把代码合入；再给 Roami 建任务修复报告链接。"
        )
        kwargs = {
            "source_turn_id": source["turnId"],
            "source_conversation_id": conversation["id"],
            "source_quote": quote,
        }
        if quote.startswith("虚构"):
            with pytest.raises(DomainError, match="TASK_STEER_SOURCE_REQUIRED"):
                await runtime.tasks.revisions.request(
                    "alice", task["id"], "Merge and release", 1, "scope", **kwargs
                )
            assert not await store.call(
                lambda db: row(db, "SELECT * FROM jobs WHERE kind='task.steer'")
            )
        else:
            receipt = await runtime.tasks.revisions.request(
                "alice", task["id"], "Merge and release", 1, "scope", **kwargs
            )
            assert receipt["text"] == quote
            await runtime.tasks.revisions.advance()
            current = (await runtime.tasks.get("alice", task["id"]))["task"]
            assert json.loads(current["intent_json"])["continuation"]["text"] == quote
    finally:
        await runtime.close()
