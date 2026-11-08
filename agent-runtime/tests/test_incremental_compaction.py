import asyncio
import copy
import json

import pytest
from test_context_provider import SummaryModel, completed_conversation

from roami_agent.context.projection import Context, context_history, fingerprint
from roami_agent.conversation.transcript import Conversations
from roami_agent.storage.database import row
from roami_agent.storage.transcript_repository import message


class RecordingSummary(SummaryModel):
    def __init__(self):
        super().__init__()
        self.prompts = []

    async def stream(self, messages, tools):
        self.prompts.append(copy.deepcopy(messages))
        async for item in super().stream(messages, tools):
            yield item


async def new_round(store, conversation):
    receipt = await Conversations(store).accept(
        "alice", conversation["id"], "next-round", "Continue the same original task. " * 20
    )

    def finish(db):
        for role, content in [
            (
                "assistant",
                {
                    "tool_calls": [
                        {
                            "id": "actual-read",
                            "type": "function",
                            "function": {"name": "read", "arguments": "{}"},
                        }
                    ]
                },
            ),
            (
                "tool",
                {"tool_call_id": "actual-read", "text": "New independently read evidence. " * 20},
            ),
            ("assistant", {"text": "New evidence is pending acceptance. " * 20}),
        ]:
            message(
                db,
                conversation["id"],
                conversation["active_branch_id"],
                role,
                content,
                turn_id=receipt["turnId"],
            )
        db.execute("UPDATE turns SET state='completed' WHERE id=?", (receipt["turnId"],))

    await store.call(finish, write=True)


async def initial_snapshot(store):
    conversation = await completed_conversation(store)
    model = RecordingSummary()
    context = Context(store, model, keep_recent_tokens=0)
    first = await context.request("alice", conversation["id"], "first-compact")
    await context.run(first["id"])
    snapshot = await store.call(lambda db: row(db, "SELECT * FROM context_snapshots"))
    assert snapshot and snapshot["state"] == "ready"
    await new_round(store, conversation)
    return conversation, context, model, snapshot


async def test_second_compaction_reuses_summary_but_retains_complete_source_identity(store):
    conversation, context, model, first = await initial_snapshot(store)
    before = await Conversations(store).messages("alice", conversation["id"])
    job = await context.request("alice", conversation["id"], "second-compact")
    await context.run(job["id"])
    assert len(model.prompts) == 2
    quoted = json.loads(model.prompts[1][1]["content"])["history"]
    assert [item["role"] for item in quoted] == ["system", "user", "assistant", "tool", "assistant"]
    assert json.loads(first["summary_json"])["text"] in quoted[0]["content"]
    assert "question " not in json.dumps(quoted)
    assert "Continue the same original task" in quoted[1]["content"]
    assert quoted[2]["tool_calls"][0]["id"] == quoted[3]["tool_call_id"]
    assert "New independently read evidence" in quoted[3]["content"]
    latest = await store.call(
        lambda db: row(db, "SELECT * FROM context_snapshots ORDER BY rowid DESC LIMIT 1")
    )
    source = await store.call(lambda db: context_history(db, conversation["active_branch_id"]))
    summary = json.loads(latest["summary_json"])
    assert summary["sourceIds"] == [item["id"] for item in source]
    assert latest["source_sha256"] == fingerprint(source)
    assert summary["previousSnapshotId"] == first["id"]
    assert (await Conversations(store).messages("alice", conversation["id"]))["messages"] == before[
        "messages"
    ]


@pytest.mark.parametrize("change", ["memory", "branch", "source", "policy", "focus", "old-cut"])
async def test_invalid_or_inapplicable_snapshot_falls_back_to_complete_history(store, change):
    conversation, context, model, first = await initial_snapshot(store)
    focus = "Revisit details absent from the old summary" if change == "focus" else ""
    if change == "memory":
        await store.call(
            lambda db: db.execute("UPDATE owner_versions SET memory_epoch=memory_epoch+1"),
            write=True,
        )
    elif change == "branch":
        await store.call(
            lambda db: db.execute(
                "UPDATE branches SET epoch=epoch+1 WHERE id=?", (conversation["active_branch_id"],)
            ),
            write=True,
        )
    elif change == "source":
        source_id = json.loads(first["summary_json"])["sourceIds"][0]
        await store.call(
            lambda db: db.execute(
                "UPDATE messages SET content_json=? WHERE id=?",
                (json.dumps({"text": "Changed original source. " * 20}), source_id),
            ),
            write=True,
        )
    elif change == "policy":
        await store.call(
            lambda db: db.execute(
                "UPDATE context_snapshots SET policy_version='unsupported-policy' WHERE id=?",
                (first["id"],),
            ),
            write=True,
        )
    elif change == "old-cut":
        context.keep_recent_tokens = 20_000
    job = await context.request("alice", conversation["id"], "second-compact", focus)
    await context.run(job["id"])
    quoted = json.loads(model.prompts[1][1]["content"])["history"]
    assert quoted[0]["role"] == "user"
    assert "question " in json.dumps(quoted) or "Changed original source" in quoted[0]["content"]
    latest = await store.call(
        lambda db: row(db, "SELECT * FROM context_snapshots ORDER BY rowid DESC LIMIT 1")
    )
    assert "previousSnapshotId" not in json.loads(latest["summary_json"])


async def test_reused_summary_does_not_bypass_full_source_check_during_activation(store):
    conversation, context, model, first = await initial_snapshot(store)
    model.started.clear()
    model.gate = asyncio.Event()
    job = await context.request("alice", conversation["id"], "second-compact")
    task = asyncio.create_task(context.run(job["id"]))
    await model.started.wait()
    source_id = json.loads(first["summary_json"])["sourceIds"][0]
    await store.call(
        lambda db: db.execute(
            "UPDATE messages SET content_json=? WHERE id=?",
            (json.dumps({"text": "Changed while summarizing"}), source_id),
        ),
        write=True,
    )
    model.gate.set()
    await task
    result = await store.call(lambda db: row(db, "SELECT * FROM jobs WHERE id=?", (job["id"],)))
    assert result["state"] == "failed"
    assert json.loads(result["payload_json"])["error"] == "COMPACTION_SOURCE_CHANGED"
    assert (
        await store.call(
            lambda db: db.execute("SELECT count(*) FROM context_snapshots").fetchone()[0]
        )
        == 1
    )
