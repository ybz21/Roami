"""Artifacts are immutable memory evidence; removed sources cannot stay in recall."""

import json

import pytest

from roami_agent.app import Runtime
from roami_agent.memory.writer import source_snapshot
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.database import row, rows


class EmptyModel:
    model = "artifact-memory-fixture"

    async def stream(self, messages, tools):
        yield ModelEvent("text", '{"memories":[]}')


@pytest.fixture
async def runtime(store):
    service = Runtime(store, EmptyModel())
    try:
        yield service
    finally:
        await service.close()


async def evidence(runtime, owner="alice", body=b"Verified report says revenue increased"):
    conversation = await runtime.conversations.create(owner)
    receipt = await runtime.conversations.accept(
        owner, conversation["id"], "artifact-source-" + conversation["id"], "Read the report"
    )
    artifact = await runtime.artifacts.put(
        owner, body, mime_type="text/plain", name="report.txt", message_id=receipt["messageId"]
    )
    return conversation, receipt, artifact


async def remember(runtime, conversation, artifact, owner="alice"):
    candidate = await runtime.memory.propose(
        owner,
        "Report fact",
        "Revenue increased",
        ["artifact:" + artifact["id"]],
        expected_sources={"artifact:" + artifact["id"]: artifact["sha256"]},
        conversation_id=conversation["id"],
    )
    return await runtime.memory.confirm(owner, candidate["id"])


async def test_artifact_source_is_scoped_and_source_deletion_invalidates_descendants(
    runtime, store
):
    conversation, receipt, artifact = await evidence(runtime)
    memory = await remember(runtime, conversation, artifact)
    sources = (await runtime.memory.get("alice", memory["id"]))["sources"]
    assert sources[0]["artifact_id"] == artifact["id"] and sources[0]["message_id"] is None
    assert sources[0]["source_sha256"] == artifact["sha256"]
    derived = await runtime.memory.save(
        "alice",
        "Derived fact",
        "Revenue increased in the report",
        receipt["messageId"],
        kind="summary",
        conversation_id=conversation["id"],
    )
    await store.call(
        lambda db: db.execute(
            "INSERT INTO memory_edges VALUES(?,?)", (memory["id"], derived["id"])
        ),
        write=True,
    )
    assert (
        len(await runtime.memory.search("alice", "Revenue", conversation_id=conversation["id"]))
        == 2
    )
    epoch = await store.call(
        lambda db: row(db, "SELECT memory_epoch FROM owner_versions WHERE owner_id='alice'")
    )
    await runtime.artifacts.delete("alice", artifact["id"])
    assert not await runtime.memory.search("alice", "Revenue", conversation_id=conversation["id"])
    records = await store.call(
        lambda db: rows(
            db, "SELECT state FROM memory_records WHERE id IN (?,?)", (memory["id"], derived["id"])
        )
    )
    assert {item["state"] for item in records} == {"candidate"}
    assert (
        await store.call(
            lambda db: row(db, "SELECT memory_epoch FROM owner_versions WHERE owner_id='alice'")
        )
    )["memory_epoch"] > epoch["memory_epoch"]
    with pytest.raises(DomainError, match="MEMORY_SOURCE_NOT_FOUND"):
        await runtime.memory.confirm("alice", memory["id"])


async def test_cross_owner_and_wrong_conversation_sources_cannot_be_confirmed(runtime):
    conversation, _, artifact = await evidence(runtime)
    other, _, _ = await evidence(runtime, "bob")
    with pytest.raises(DomainError, match="MEMORY_SOURCE_NOT_FOUND"):
        await runtime.memory.propose(
            "bob",
            "Other source",
            "must not leak",
            ["artifact:" + artifact["id"]],
            expected_sources={"artifact:" + artifact["id"]: artifact["sha256"]},
            conversation_id=other["id"],
        )
    second = await runtime.conversations.create("alice")
    with pytest.raises(DomainError, match="MEMORY_SOURCE_SCOPE_MISMATCH"):
        await runtime.memory.propose(
            "alice",
            "Other conversation",
            "wrong scope",
            ["artifact:" + artifact["id"]],
            expected_sources={"artifact:" + artifact["id"]: artifact["sha256"]},
            conversation_id=second["id"],
        )
    snapshot = await runtime.db.call(
        lambda db: source_snapshot(db, "alice", "artifact:" + artifact["id"])
    )
    assert (
        snapshot["conversation_id"] == conversation["id"] and "path" not in snapshot["content_json"]
    )


async def test_forgetting_artifact_memory_blocks_model_reads_but_keeps_user_visible_evidence(
    runtime, store
):
    conversation, receipt, artifact = await evidence(runtime)
    memory = await remember(runtime, conversation, artifact)
    await runtime.memory.forget("alice", memory["id"])
    assert await store.call(
        lambda db: row(
            db,
            "SELECT message_id FROM context_omissions WHERE message_id=?",
            (receipt["messageId"],),
        )
    )
    with pytest.raises(DomainError, match="MEMORY_FORGOTTEN"):
        await runtime.tools.invoke(
            {
                "function": {
                    "name": "artifact_read",
                    "arguments": json.dumps({"id": artifact["id"]}),
                }
            },
            "worker",
            {"owner": "alice"},
        )
    assert (await runtime.artifacts.read("alice", artifact["id"]))[1].startswith(b"Verified report")


async def test_deleting_one_reference_does_not_invalidate_other_owners_identical_content(runtime):
    conversation, _, artifact = await evidence(runtime)
    other, _, duplicate = await evidence(runtime, "bob")
    assert artifact["sha256"] == duplicate["sha256"]
    await remember(runtime, conversation, artifact)
    other_memory = await remember(runtime, other, duplicate, "bob")
    await runtime.artifacts.delete("alice", artifact["id"])
    assert (await runtime.memory.get("bob", other_memory["id"]))["state"] == "active"
    assert len(await runtime.memory.search("bob", "Revenue")) == 1


async def test_extraction_records_artifact_dependencies_even_when_model_only_cites_the_message(
    runtime, store
):
    conversation, receipt, artifact = await evidence(runtime)
    cursor = await store.call(
        lambda db: (
            db.execute(
                "INSERT INTO events(conversation_id,message_id,event_key,kind,payload_json,created_ms) VALUES(?,?,?,'message.completed','{}',?)",
                (
                    conversation["id"],
                    receipt["messageId"],
                    "artifact-extraction",
                    artifact["createdMs"] + 1,
                ),
            ).lastrowid
        ),
        write=True,
    )
    sources, _ = await store.call(
        lambda db: runtime.memory_jobs._sources(db, {"owner": "alice", "eventId": cursor})
    )
    assert "artifact:" + artifact["id"] in {source["id"] for source in sources}

    class IncompleteCitation:
        model = "artifact-citation-fixture"

        async def stream(self, messages, tools):
            assert "Verified report says revenue increased" in messages[-1]["content"]
            yield ModelEvent(
                "text",
                json.dumps(
                    {
                        "memories": [
                            {
                                "title": "Extracted report",
                                "body": "Revenue increased",
                                "kind": "fact",
                                "sourceIds": [receipt["messageId"]],
                            }
                        ]
                    }
                ),
            )

    runtime.memory_jobs.model = IncompleteCitation()
    await runtime.memory_jobs.scan()
    job = await store.call(
        lambda db: row(
            db,
            "SELECT * FROM jobs WHERE kind='memory.extract' AND json_extract(payload_json,'$.eventId')=?",
            (cursor,),
        )
    )
    await runtime.memory_jobs.run(job)
    candidates = await runtime.memory.candidates("alice", conversation_id=conversation["id"])
    assert len(candidates) == 1
    assert artifact["id"] in {source["artifact_id"] for source in candidates[0]["sourceRefs"]}
    await runtime.artifacts.delete("alice", artifact["id"])
    with pytest.raises(DomainError, match="MEMORY_SOURCE_NOT_FOUND"):
        await runtime.memory.confirm("alice", candidates[0]["id"])


async def test_missing_artifact_filter_runs_before_candidate_limit_for_legacy_records(
    runtime, store
):
    conversation, receipt, artifact = await evidence(runtime)
    for index in range(45):
        await runtime.memory.save(
            "alice",
            "Artifact fact " + str(index),
            "Revenue increased",
            "artifact:" + artifact["id"],
            conversation_id=conversation["id"],
        )
    valid = await runtime.memory.save(
        "alice",
        "Valid source",
        "Revenue increased",
        receipt["messageId"],
        conversation_id=conversation["id"],
    )
    await store.call(
        lambda db: db.execute("UPDATE memory_records SET updated_ms=0 WHERE id=?", (valid["id"],)),
        write=True,
    )
    await store.call(
        lambda db: db.execute("UPDATE artifacts SET deleted_ms=1 WHERE id=?", (artifact["id"],)),
        write=True,
    )
    hits = await runtime.memory.search("alice", "", conversation_id=conversation["id"], limit=1)
    assert [hit["id"] for hit in hits] == [valid["id"]]


async def test_source_removed_during_model_extraction_cannot_be_committed(runtime, store):
    import asyncio

    conversation, receipt, artifact = await evidence(runtime)
    cursor = await store.call(
        lambda db: (
            db.execute(
                "INSERT INTO events(conversation_id,message_id,event_key,kind,payload_json,created_ms) VALUES(?,?,?,'message.completed','{}',?)",
                (
                    conversation["id"],
                    receipt["messageId"],
                    "artifact-extraction-race",
                    artifact["createdMs"] + 1,
                ),
            ).lastrowid
        ),
        write=True,
    )
    entered, release = asyncio.Event(), asyncio.Event()

    class DelayedExtraction:
        model = "delayed-artifact-extraction"

        async def stream(self, messages, tools):
            entered.set()
            await release.wait()
            yield ModelEvent(
                "text",
                json.dumps(
                    {
                        "memories": [
                            {
                                "title": "Late proposal",
                                "body": "Revenue increased",
                                "kind": "fact",
                                "sourceIds": [receipt["messageId"]],
                            }
                        ]
                    }
                ),
            )

    runtime.memory_jobs.model = DelayedExtraction()
    await runtime.memory_jobs.scan()
    job = await store.call(
        lambda db: row(
            db,
            "SELECT * FROM jobs WHERE kind='memory.extract' AND json_extract(payload_json,'$.eventId')=?",
            (cursor,),
        )
    )
    extraction = asyncio.create_task(runtime.memory_jobs.run(job))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await runtime.artifacts.delete("alice", artifact["id"])
    finally:
        release.set()
    await extraction
    assert not await runtime.memory.candidates("alice")
    assert (
        await store.call(lambda db: row(db, "SELECT state FROM jobs WHERE id=?", (job["id"],)))
    )["state"] == "failed"


@pytest.mark.parametrize(
    "tool_name, remove",
    [("artifact_read", "delete"), ("artifact_read", "forget"), ("memory_get", "forget")],
)
async def test_tool_result_commit_revalidates_sources_after_reading(
    runtime, store, monkeypatch, tool_name, remove
):
    import asyncio

    conversation, _, artifact = await evidence(runtime)
    memory = await remember(runtime, conversation, artifact)
    target = await runtime.conversations.create("alice")
    receipt = await runtime.conversations.accept(
        "alice", target["id"], "source-race", "Read the referenced source"
    )

    def running(db):
        db.execute("UPDATE turns SET state='running' WHERE id=?", (receipt["turnId"],))
        return dict(
            row(db, "SELECT * FROM turns WHERE id=?", (receipt["turnId"],)), owner_id="alice"
        )

    turn = await store.call(running, write=True)
    mid = await runtime.journal.start(turn)
    entered, release = asyncio.Event(), asyncio.Event()
    tool = runtime.tools.registry[tool_name]
    original = tool.handler

    async def delayed(args, binding):
        value = await original(args, binding)
        entered.set()
        await release.wait()
        return value

    monkeypatch.setattr(tool, "handler", delayed)
    args = {"id": artifact["id"]} if tool_name == "artifact_read" else {"memoryId": memory["id"]}
    call = {
        "id": "source-race",
        "type": "function",
        "function": {"name": tool_name, "arguments": json.dumps(args)},
    }
    invocation = asyncio.create_task(
        runtime.gateway.invoke(
            turn, mid, call, "worker", {"owner": "alice", "conversation": target["id"]}
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        if remove == "delete":
            await runtime.artifacts.delete("alice", artifact["id"])
        else:
            await runtime.memory.forget("alice", memory["id"])
    finally:
        release.set()
    result = await invocation
    assert result["error"] in {"ARTIFACT_SOURCE_UNAVAILABLE", "MEMORY_SOURCE_CHANGED"}
    stored = await store.call(
        lambda db: row(
            db,
            "SELECT m.content_json,x.state FROM tool_calls x JOIN messages m ON m.id=x.result_message_id WHERE x.turn_id=?",
            (turn["id"],),
        )
    )
    assert stored["state"] == "failed"
    assert (
        "Verified report" not in stored["content_json"]
        and "Revenue increased" not in stored["content_json"]
    )
