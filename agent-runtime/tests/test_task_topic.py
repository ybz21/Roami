"""Task topics persist without changing the full goal or legacy request identity."""

import json

import pytest
from test_runtime import ConversationModel, until

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row


async def test_topic_is_optional_normalized_and_part_of_idempotency(store):
    runtime = Runtime(store, ConversationModel())
    try:
        conversation = await runtime.conversations.create("alice")
        cid = conversation["id"]
        legacy = await runtime.tasks.create(
            "alice", cid, "Full legacy goal", key="legacy", record_intent=True
        )
        assert "title" not in json.loads(legacy["intent_json"])
        assert (
            await runtime.tasks.create(
                "alice", cid, "Full legacy goal", key="legacy", record_intent=True
            )
        )["id"] == legacy["id"]
        task = await runtime.tasks.create(
            "alice",
            cid,
            "Detailed requirements and steps",
            title="  制作无人机集群   PPT ",
            key="topic",
            record_intent=True,
        )
        intent = json.loads(task["intent_json"])
        assert intent["title"] == "制作无人机集群 PPT"
        assert intent["goal"] == "Detailed requirements and steps"
        replay = await runtime.tasks.create(
            "alice", cid, intent["goal"], title=intent["title"], key="topic", record_intent=True
        )
        assert replay["id"] == task["id"]
        with pytest.raises(DomainError, match="TASK_KEY_CONFLICT"):
            await runtime.tasks.create(
                "alice",
                cid,
                intent["goal"],
                title="Different topic",
                key="topic",
                record_intent=True,
            )
        operation = await runtime.tasks.revisions.request(
            "alice", task["id"], "Also check sources", 1, "continue"
        )
        await runtime.start()
        await until(
            store,
            lambda db: (
                row(db, "SELECT revision FROM tasks WHERE id=?", (task["id"],))["revision"] == 2
            ),
        )
        assert (await runtime.tasks.revisions.get("alice", task["id"], operation["operationId"]))[
            "state"
        ] == "applied"
        continued = await runtime.tasks.get("alice", task["id"])
        assert (
            json.loads(continued["task"]["intent_json"])["initialIntent"]["title"]
            == intent["title"]
        )
    finally:
        await runtime.close()


@pytest.mark.parametrize("title", ["", "   ", 42, "a" * 81])
async def test_invalid_topic_cannot_create_a_task(store, title):
    runtime = Runtime(store, ConversationModel())
    try:
        conversation = await runtime.conversations.create("alice")
        with pytest.raises(DomainError, match="INVALID_TASK"):
            await runtime.tasks.create(
                "alice", conversation["id"], "Full goal", key="invalid", title=title
            )
    finally:
        await runtime.close()


async def test_inspector_exposes_current_verification_failure_without_rewriting_executor_report(
    store,
):
    import asyncio

    from roami_agent.protocol.models import ModelEvent

    class Research:
        model = "research-verdict"
        calls = 0

        def __init__(self):
            self.boundaries = []
            self.continued = asyncio.Event()

        async def stream(self, messages, tools):
            boundary = [
                m["content"]
                for m in messages
                if m["role"] == "system" and m["content"].startswith("Current research attempt:")
            ]
            if not boundary:
                yield ModelEvent("text", '{"memories":[]}')
                return
            self.calls += 1
            self.boundaries.append(boundary)
            if self.calls > 1:
                self.continued.set()
                await asyncio.Event().wait()
            yield ModelEvent("text", "Candidate says success but has no retrieved source")

    research = Research()
    runtime = Runtime(store, ConversationModel(), worker_model=research)
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            conversation["id"],
            "Read public weather",
            key="verdict",
            record_intent=True,
            target={"kind": "new_session", "resourceOnly": True},
        )
        await runtime.start()
        await until(
            store,
            lambda db: (
                row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],))["state"] == "failed"
            ),
        )
        detail = await runtime.tasks.get("alice", task["id"])
        assert len(research.boundaries[0]) == 1
        assert detail["attempts"][0]["id"] in research.boundaries[0][0]
        assert detail["outcome"] == {
            "state": "failed",
            "errorCode": "WEB_RETRIEVAL_EVIDENCE_MISSING",
        }
        assert detail["attempts"][0]["state"] == "succeeded"
        assert (
            detail["attempts"][0]["result"]["summary"]
            == "Candidate says success but has no retrieved source"
        )
        await runtime.tasks.revisions.request("alice", task["id"], "Continue", 1, "next")
        await until(
            store,
            lambda db: (
                row(db, "SELECT revision FROM tasks WHERE id=?", (task["id"],))["revision"] == 2
            ),
        )
        assert (await runtime.tasks.get("alice", task["id"]))["outcome"] is None
        await asyncio.wait_for(research.continued.wait(), 2)
        assert len(research.boundaries[1]) == 1
        assert research.boundaries[0] != research.boundaries[1]
    finally:
        await runtime.close()
