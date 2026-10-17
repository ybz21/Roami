import asyncio
import json
from datetime import UTC, datetime

import pytest
from test_runtime import ConversationModel, until

from roami_agent.app import Runtime
from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.tasks import Tasks
from roami_agent.memory.daily import DailyMemories, day_bounds
from roami_agent.memory.records import Memories
from roami_agent.memory.writer import source_snapshot
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.database import event, row, rows


async def source(store, owner="alice", text="以后用中文回答"):
    conversations = Conversations(store)
    conversation = await conversations.create(owner)
    receipt = await conversations.accept(
        owner, conversation["id"], "source-" + conversation["id"], text
    )
    snapshot = await store.call(lambda db: source_snapshot(db, owner, receipt["messageId"]))
    return conversation, receipt, snapshot


async def test_inferred_candidates_conflicts_confirmation_and_source_scope(store):
    memory = Memories(store)
    c, receipt, snapshot = await source(store)
    args = ("alice", "回复语言", "中文", [receipt["messageId"]])
    candidate = await memory.propose(
        *args,
        expected_sources={snapshot["id"]: snapshot["sha256"]},
        kind="preference",
        conversation_id=c["id"],
    )
    assert candidate["state"] == "candidate"
    assert await memory.search("alice", "中文", conversation_id=c["id"]) == []
    active = await memory.confirm("alice", candidate["id"])
    assert active["state"] == "active" and active["revision"] == 2
    conflict = await memory.propose(
        "alice",
        "回复语言",
        "英文",
        [snapshot["id"]],
        expected_sources={snapshot["id"]: snapshot["sha256"]},
        kind="preference",
        conversation_id=c["id"],
    )
    assert conflict["state"] == "conflict"
    assert (await memory.get("alice", active["id"]))["body"] == "中文"
    assert (await memory.confirm("alice", conflict["id"]))["body"] == "英文"
    with pytest.raises(DomainError, match="MEMORY_NOT_FOUND"):
        await memory.get("alice", active["id"])
    other = await Conversations(store).create("alice")
    with pytest.raises(DomainError, match="MEMORY_SOURCE_SCOPE_MISMATCH"):
        await memory.save(
            "alice", "Wrong scope", "wrong", snapshot["id"], conversation_id=other["id"]
        )
    with pytest.raises(DomainError, match="MEMORY_SOURCE_NOT_FOUND"):
        await memory.propose(
            "bob",
            "Wrong owner",
            "wrong",
            [snapshot["id"]],
            expected_sources={snapshot["id"]: snapshot["sha256"]},
        )
    with pytest.raises(DomainError, match="MEMORY_SOURCE_CHANGED"):
        await memory.propose(
            "alice",
            "Changed source",
            "wrong",
            [snapshot["id"]],
            expected_sources={snapshot["id"]: "stale"},
        )


async def test_retrieval_literal_or_scope_validity_and_bounded_character_fallback(store):
    memory = Memories(store)
    c, receipt, _ = await source(store)
    good = await memory.save(
        "alice", "Agent 会话方案", "Python 处理会话", receipt["messageId"], conversation_id=c["id"]
    )
    result = await memory.recall("alice", "会话 missing", conversation_id=c["id"], limit=8)
    assert result["hits"][0]["id"] == good["id"]
    assert result["hits"][0]["sourceRefs"][0]["message_id"] == receipt["messageId"]
    assert result["memoryEpoch"] >= 2 and result["tokenizerVersion"] == "cjk-bigram-v2"
    assert await memory.search("alice", '" OR *', conversation_id=c["id"]) == []
    assert (await memory.search("alice", "话", conversation_id=c["id"]))[0]["id"] == good["id"]
    await store.call(
        lambda db: db.execute(
            "UPDATE memory_records SET valid_until_ms=? WHERE id=?", (now_ms() - 1, good["id"])
        ),
        write=True,
    )
    assert await memory.search("alice", "Python", conversation_id=c["id"]) == []
    with pytest.raises(DomainError, match="MEMORY_NOT_FOUND"):
        await memory.get("alice", good["id"])
    await store.call(
        lambda db: db.execute(
            "UPDATE memory_records SET valid_until_ms=NULL,valid_from_ms=? WHERE id=?",
            (now_ms() + 100_000, good["id"]),
        ),
        write=True,
    )
    assert await memory.search("alice", "Python", conversation_id=c["id"]) == []
    await store.call(
        lambda db: db.execute(
            "UPDATE memory_records SET valid_from_ms=1 WHERE id=?", (good["id"],)
        ),
        write=True,
    )
    other, other_receipt, _ = await source(store, "bob")
    for index in range(45):
        await memory.save(
            "bob",
            str(index),
            "Python 会话",
            other_receipt["messageId"],
            conversation_id=other["id"],
        )
    assert [
        hit["id"] for hit in await memory.search("alice", "Python", conversation_id=c["id"])
    ] == [good["id"]]

    def recent(db):
        for index in range(501):
            db.execute(
                "INSERT INTO memory_records(id,owner_id,kind,conversation_id,title,body,search_tokens,state,valid_from_ms,created_ms,updated_ms) VALUES(?,'alice','fact',?,'recent','other','other','active',1,?,?)",
                ("recent-" + str(index), c["id"], now_ms() + index, now_ms() + index),
            )

    await store.call(recent, write=True)
    assert await memory.search("alice", "话", conversation_id=c["id"]) == []


def timestamp(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp() * 1000)


async def test_daily_unique_counts_cross_day_late_events_and_no_resurrection(store):
    c, _receipt, _ = await source(store)
    tasks = Tasks(store, Conversations(store))
    task = await tasks.create(
        "alice",
        c["id"],
        "project task",
        key="one",
        executor="codex",
        target={"kind": "project", "projectId": "project-a"},
    )
    assert (
        await tasks.create(
            "alice",
            c["id"],
            "project task",
            key="one",
            executor="codex",
            target={"kind": "project", "projectId": "project-a"},
        )
    )["id"] == task["id"]
    first = timestamp("2024-01-01T08:00:00")
    second = timestamp("2024-01-02T02:00:00")

    def dated(db):
        db.execute("UPDATE events SET created_ms=?", (first,))
        db.execute("UPDATE messages SET created_ms=?", (first,))
        for key in ["completion-one", "completion-replay"]:
            ident = event(
                db, c["id"], "task.succeeded", {"state": "succeeded"}, key=key, task_id=task["id"]
            )
            db.execute("UPDATE events SET created_ms=? WHERE id=?", (second, ident))

    await store.call(dated, write=True)
    daily = DailyMemories(store, "Asia/Shanghai")
    await daily.refresh("alice", "2024-01-01")
    await daily.refresh("alice", "2024-01-02")
    snapshots = await store.call(
        lambda db: rows(db, "SELECT * FROM day_summaries ORDER BY day_key")
    )
    assert len(snapshots) == 2
    a, b = [json.loads(entry["counts_json"]) for entry in snapshots]
    assert (a["userTurns"], a["tasksCreated"], a["tasksCompleted"]) == (1, 1, 0)
    assert (b["userTurns"], b["tasksCreated"], b["tasksCompleted"]) == (0, 0, 1)
    again = await daily.refresh("alice", "2024-01-01")
    assert again == [snapshots[0]["memory_id"]]
    late = await Conversations(store).accept("alice", c["id"], "late", "late user input")
    await store.call(
        lambda db: db.execute(
            "UPDATE events SET created_ms=? WHERE message_id=?", (first + 1, late["messageId"])
        ),
        write=True,
    )
    await daily.refresh("alice", "2024-01-01")
    current = await store.call(
        lambda db: rows(
            db, "SELECT * FROM day_summaries WHERE day_key='2024-01-01' ORDER BY scope_key"
        )
    )
    assert [entry["scope_key"] for entry in current] == ["project-a", "unassigned"]
    assert json.loads(current[1]["counts_json"])["userTurns"] == 1
    assert current[0]["revision"] == 1
    assert current[0]["source_watermark"] > snapshots[0]["source_watermark"]
    assert await daily.refresh("bob", "2024-01-01") == []
    await Memories(store).delete("alice", current[1]["memory_id"])
    await daily.refresh("alice", "2024-01-01")
    assert (
        await store.call(
            lambda db: row(
                db, "SELECT state FROM memory_records WHERE id=?", (current[1]["memory_id"],)
            )
        )
    )["state"] == "deleted"


def test_daily_uses_real_local_day_boundaries():
    assert (
        day_bounds("2024-03-10", "America/New_York")[1]
        - day_bounds("2024-03-10", "America/New_York")[0]
        == 23 * 3_600_000
    )
    assert (
        day_bounds("2024-11-03", "America/New_York")[1]
        - day_bounds("2024-11-03", "America/New_York")[0]
        == 25 * 3_600_000
    )
    with pytest.raises(DomainError, match="INVALID_MEMORY_DAY"):
        day_bounds("2024-02-30", "UTC")


class ProposalModel:
    model = "memory-extractor-fixture"

    def __init__(self, gate=None, invalid=False):
        self.started = asyncio.Event()
        self.gate, self.invalid = gate, invalid
        self.calls = 0

    async def stream(self, messages, tools):
        assert not tools
        self.calls += 1
        self.started.set()
        if self.gate:
            await self.gate.wait()
        evidence = json.loads(messages[-1]["content"])
        source_id = "foreign-source" if self.invalid else evidence[0]["id"]
        yield ModelEvent(
            "text",
            json.dumps(
                {
                    "memories": [
                        {
                            "title": "回复语言",
                            "body": "使用中文",
                            "kind": "preference",
                            "sourceIds": [source_id],
                        }
                    ]
                }
            ),
        )
        yield ModelEvent("usage", {"input_tokens": 12, "output_tokens": 8})


async def test_background_proposals_are_durable_scoped_and_not_active(store):
    extractor = ProposalModel()
    runtime = Runtime(store, ConversationModel(), memory_model=extractor)
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        await runtime.chat.submit("alice", c["id"], "first", "以后用中文回答")
        await until(
            store, lambda db: row(db, "SELECT id FROM memory_records WHERE state='candidate'")
        )
        candidates = await runtime.memory.candidates("alice", conversation_id=c["id"])
        assert len(candidates) == 1 and candidates[0]["conversation_id"] == c["id"]
        assert await runtime.memory.search("alice", "中文", conversation_id=c["id"]) == []
        await runtime.memory_jobs.scan()
        await runtime.memory_jobs.scan()
        assert extractor.calls == 1
        job = await store.call(lambda db: row(db, "SELECT * FROM jobs WHERE kind='memory.extract'"))
        assert job["state"] == "done"
        assert json.loads(job["payload_json"])["usage"]["input_tokens"] == 12
        assert (await runtime.memory.confirm("alice", candidates[0]["id"]))["state"] == "active"
        assert (
            await runtime.memory.get(
                "alice", (await runtime.memory.search("alice", "中文"))[0]["id"]
            )
        )["sources"]
    finally:
        await runtime.close()


async def test_slow_memory_keeps_main_capacity_and_cancellation_requeues(store):
    gate = asyncio.Event()
    extractor = ProposalModel(gate)
    runtime = Runtime(store, ConversationModel(), memory_model=extractor)
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        await runtime.chat.submit("alice", c["id"], "one", "first")
        await asyncio.wait_for(extractor.started.wait(), 3)
        second = await runtime.chat.submit("alice", c["id"], "two", "second")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (second["turnId"],)
            ),
            timeout=2,
        )
        assert not gate.is_set()
    finally:
        await runtime.close()
    assert await store.call(
        lambda db: row(db, "SELECT id FROM jobs WHERE kind='memory.extract' AND state='queued'")
    )


@pytest.mark.parametrize("forget,invalid", [(True, False), (False, True)])
async def test_extraction_rejects_forgotten_or_invented_sources_atomically(store, forget, invalid):
    gate = asyncio.Event()
    extractor = ProposalModel(gate, invalid)
    runtime = Runtime(store, ConversationModel(), memory_model=extractor)
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "one", "private source")
        await asyncio.wait_for(extractor.started.wait(), 3)
        if forget:
            saved = await runtime.memory.save(
                "alice", "private", "private source", receipt["messageId"], conversation_id=c["id"]
            )
            await runtime.memory.forget("alice", saved["id"])
        gate.set()
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM jobs WHERE kind='memory.extract' AND state='failed'"
            ),
        )
        assert await runtime.memory.candidates("alice") == []
    finally:
        await runtime.close()


async def test_ordinary_delete_invalidates_derived_memories_but_forget_tracks_prompt_dependencies(
    store,
):
    runtime = Runtime(store, ConversationModel())
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "one", "private detail")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
        )
        second = await runtime.chat.submit("alice", c["id"], "two", "follow-up")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (second["turnId"],)
            ),
        )
        memory = await runtime.memory.save(
            "alice", "private", "private detail", receipt["messageId"], conversation_id=c["id"]
        )
        derived = await runtime.memory.save(
            "alice",
            "derived",
            "derived summary",
            second["messageId"],
            conversation_id=c["id"],
            kind="summary",
        )
        independent = await runtime.memory.save(
            "alice",
            "other fact",
            "unrelated knowledge",
            receipt["messageId"],
            conversation_id=c["id"],
        )
        await store.call(
            lambda db: db.execute(
                "INSERT INTO memory_edges VALUES(?,?)", (memory["id"], derived["id"])
            ),
            write=True,
        )
        await runtime.memory.delete("alice", memory["id"])
        assert (
            await store.call(
                lambda db: row(db, "SELECT state FROM memory_records WHERE id=?", (derived["id"],))
            )
        )["state"] == "candidate"
        assert "private detail" in json.dumps(
            (await runtime.context.project("alice", c["id"]))["messages"]
        )
        await runtime.memory.forget("alice", memory["id"])
        plan = await runtime.context.project("alice", c["id"])
        assert "private detail" not in json.dumps(plan["messages"])
        assert "follow-up" in json.dumps(plan["messages"])
        assert (await runtime.memory.get("alice", independent["id"]))["state"] == "active"
        transcript = await runtime.conversations.messages("alice", c["id"])
        assert len(transcript["messages"]) == 4
        manifests = await store.call(
            lambda db: rows(db, "SELECT * FROM prompt_manifests ORDER BY created_ms")
        )
        assert all(json.loads(item["parts_json"])["sourceMessageIds"] for item in manifests)
        snapshot = await store.call(lambda db: source_snapshot(db, "alice", receipt["messageId"]))
        with pytest.raises(DomainError, match="MEMORY_FORGOTTEN"):
            await runtime.memory.propose(
                "alice",
                "renamed inference",
                "private detail",
                [snapshot["id"]],
                expected_sources={snapshot["id"]: snapshot["sha256"]},
            )
    finally:
        await runtime.close()


async def test_archive_jobs_coalesce_and_wait_for_local_midnight(store):
    runtime = Runtime(store, ConversationModel(), memory_model=ProposalModel())
    c = await runtime.conversations.create("alice")
    for index in range(35):
        await runtime.conversations.accept("alice", c["id"], "day-" + str(index), "one request")
    for _ in range(4):
        await runtime.memory_jobs.scan()
    jobs = await store.call(lambda db: rows(db, "SELECT * FROM jobs WHERE kind='memory.daily'"))
    assert len(jobs) == 1
    payload = json.loads(jobs[0]["payload_json"])
    assert jobs[0]["available_ms"] == day_bounds(payload["dayKey"], payload["timezone"])[1]
    assert jobs[0]["available_ms"] > now_ms()
    before = json.loads(
        (
            await store.call(
                lambda db: row(db, "SELECT payload_json FROM jobs WHERE kind='memory.scan'")
            )
        )["payload_json"]
    )["cursor"]
    after = await store.call(lambda db: db.execute("SELECT MAX(id) FROM events").fetchone()[0])
    assert before == after
    await runtime.close()


async def test_interrupted_memory_job_recovery_and_completion_replay(store):
    extractor = ProposalModel()
    runtime = Runtime(store, ConversationModel(), memory_model=extractor)
    c, receipt, _ = await source(store)
    from roami_agent.storage.transcript_repository import message

    def finish(db):
        mid = message(
            db,
            c["id"],
            c["active_branch_id"],
            "assistant",
            {"text": "明白"},
            turn_id=receipt["turnId"],
        )
        event(
            db,
            c["id"],
            "message.completed",
            {"messageId": mid},
            message_id=mid,
            turn_id=receipt["turnId"],
        )
        db.execute("UPDATE turns SET state='completed' WHERE id=?", (receipt["turnId"],))

    await store.call(finish, write=True)
    await runtime.memory_jobs.scan()
    job = await store.call(lambda db: row(db, "SELECT * FROM jobs WHERE kind='memory.extract'"))
    await store.call(
        lambda db: db.execute(
            "UPDATE jobs SET state='running',attempts=1 WHERE id=?", (job["id"],)
        ),
        write=True,
    )
    await runtime.memory_jobs.recover()
    await runtime.memory_jobs.run(job)
    await runtime.memory_jobs.run(job)
    assert extractor.calls == 1
    assert len(await runtime.memory.candidates("alice")) == 1
    await runtime.close()


async def test_memory_http_scope_review_sources_and_delete_modes(store):
    import httpx

    from roami_agent.server.http import create_app

    runtime = Runtime(store, ConversationModel())
    c, receipt, snapshot = await source(store, text="原始来源")
    candidate = await runtime.memory.propose(
        "alice",
        "待确认",
        "中文偏好",
        [receipt["messageId"]],
        kind="preference",
        conversation_id=c["id"],
        expected_sources={snapshot["id"]: snapshot["sha256"]},
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
            base_url="http://agent",
            headers={"X-Roami-Owner": "alice"},
        ) as client:
            pending = await client.get(
                "/v1/memories",
                params={
                    "state": "candidate",
                    "kind": "preference",
                    "conversationId": c["id"],
                    "query": "待",
                },
            )
            assert [entry["id"] for entry in pending.json()["data"]] == [candidate["id"]]
            assert (
                await client.get("/v1/memories", params={"state": "candidate", "query": "%"})
            ).json()["data"] == []
            assert (
                await client.get(
                    "/v1/memories/" + candidate["id"] + "/sources", headers={"X-Roami-Owner": "bob"}
                )
            ).status_code == 404
            evidence = (await client.get("/v1/memories/" + candidate["id"] + "/sources")).json()[
                "data"
            ]
            assert evidence[0]["text"] == "原始来源" and evidence[0]["unchanged"]
            confirmed = await client.post(
                "/v1/memories/" + candidate["id"] + "/confirm", json={"accepted": True}
            )
            assert confirmed.status_code == 200
            ident = confirmed.json()["data"]["id"]
            assert (
                await client.post(
                    "/v1/memories/" + candidate["id"] + "/confirm", json={"accepted": True}
                )
            ).json()["data"]["id"] == ident
            assert (
                await client.post(
                    "/v1/memories/" + candidate["id"] + "/confirm", json={"accepted": False}
                )
            ).status_code == 409
            assert (
                await client.delete("/v1/memories/" + ident, params={"forgetSources": "false"})
            ).status_code == 200
            assert not await store.call(
                lambda db: row(db, "SELECT message_id FROM context_omissions")
            )
            assert (
                await client.delete("/v1/memories/" + ident, params={"forgetSources": "true"})
            ).status_code == 200
            assert await store.call(lambda db: row(db, "SELECT message_id FROM context_omissions"))
    finally:
        await runtime.close()


@pytest.mark.parametrize("legacy", [False, True])
async def test_forgetting_follows_cross_conversation_memory_tools(store, legacy):
    class RecallModel:
        model = "memory-recall-fixture"

        async def stream(self, messages, tools):
            if messages[-1]["role"] == "tool":
                yield ModelEvent("text", "derived private answer")
            else:
                yield ModelEvent(
                    "tool",
                    {
                        "id": "recall-private",
                        "type": "function",
                        "function": {
                            "name": "memory_get",
                            "arguments": json.dumps({"memoryId": saved["id"]}),
                        },
                    },
                )

    runtime = Runtime(store, RecallModel(), memory_model=ConversationModel())
    _, receipt, _ = await source(store, text="private origin")
    saved = await runtime.memory.save("alice", "private", "private origin", receipt["messageId"])
    target = await runtime.conversations.create("alice")
    await runtime.start()
    try:
        reply = await runtime.chat.submit("alice", target["id"], "recall", "recall the preference")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (reply["turnId"],)
            ),
        )
        if legacy:

            def erase_modern_metadata(db):
                db.execute(
                    "UPDATE messages SET content_json=json_remove(content_json,'$.memoryIds') WHERE conversation_id=? AND role='tool'",
                    (target["id"],),
                )
                db.execute(
                    "UPDATE prompt_manifests SET parts_json=json_remove(parts_json,'$.sourceMessageIds') WHERE turn_id IN (SELECT id FROM turns WHERE conversation_id=?)",
                    (target["id"],),
                )

            await store.call(erase_modern_metadata, write=True)
        before = await runtime.context.project("alice", target["id"])
        assert "private origin" in json.dumps(before["messages"])
        await runtime.memory.forget("alice", saved["id"])
        after = json.dumps((await runtime.context.project("alice", target["id"]))["messages"])
        assert "private origin" not in after and "derived private answer" not in after
        assert "recall the preference" in after
        assert len((await runtime.conversations.messages("alice", target["id"]))["messages"]) == 4
    finally:
        await runtime.close()


async def test_forgotten_task_origin_prevents_dispatch_and_redacts_completion(store):
    from roami_agent.context.prompt_builder import PromptBuilder

    class NeverRun:
        async def run(self, *args, **kwargs):
            pytest.fail("Forgotten task input reached the executor")

    runtime = Runtime(store, ConversationModel())
    c, receipt, _ = await source(store, text="secret task input")
    task = await runtime.tasks.create(
        "alice",
        c["id"],
        "secret task input",
        key="forgotten-task",
        origin_message_id=receipt["messageId"],
    )
    saved = await runtime.memory.save("alice", "private", "secret task input", receipt["messageId"])
    await runtime.memory.forget("alice", saved["id"])
    job = await store.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE aggregate_id=? AND kind='task.run'", (task["id"],)
        )
    )
    runtime.dispatch.native_executor = NeverRun()
    await runtime.dispatch.run(job)
    failed = await store.call(lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],)))
    assert failed["state"] == "failed"
    builder = PromptBuilder(store, runtime.context, runtime.settings)
    turn = await store.call(
        lambda db: dict(
            row(db, "SELECT * FROM turns WHERE id=?", (receipt["turnId"],)), owner_id="alice"
        )
    )
    _, prompt = await builder.build(
        turn,
        "instructions",
        [],
        {"taskId": task["id"], "state": "succeeded", "result": {"summary": "secret task output"}},
    )
    assert "secret task" not in json.dumps(prompt)
    assert "contextExcluded" in json.dumps(prompt)
    await runtime.close()


async def test_explicit_relearning_requires_a_new_source_and_version(store):
    memory = Memories(store)
    c, receipt, _ = await source(store, text="简洁回答")
    saved = await memory.save("alice", "偏好", "简洁回答", receipt["messageId"])
    await memory.forget("alice", saved["id"])
    with pytest.raises(DomainError, match="MEMORY_FORGOTTEN"):
        await memory.save("alice", "偏好", "简洁回答", receipt["messageId"])
    fresh = await Conversations(store).accept("alice", c["id"], "relearn", "简洁回答")
    snapshot = await store.call(lambda db: source_snapshot(db, "alice", fresh["messageId"]))
    with pytest.raises(DomainError, match="MEMORY_FORGOTTEN"):
        await memory.propose(
            "alice",
            "偏好",
            "简洁回答",
            [snapshot["id"]],
            expected_sources={snapshot["id"]: snapshot["sha256"]},
        )
    remembered = await memory.save("alice", "偏好", "简洁回答", fresh["messageId"])
    assert remembered["revision"] == saved["revision"] + 1
    assert (await memory.get("alice", remembered["id"]))["sources"][0]["message_id"] == fresh[
        "messageId"
    ]
    assert await store.call(lambda db: row(db, "SELECT * FROM memory_tombstones"))


async def test_forgetting_during_model_stream_prevents_new_task_tool(store):
    class PausedRecall:
        model = "paused-memory-recall"

        def __init__(self):
            self.started, self.release = asyncio.Event(), asyncio.Event()

        async def stream(self, messages, tools):
            if messages[-1]["role"] == "tool":
                self.started.set()
                await self.release.wait()
                name, args = "delegate", {"goal": "repeat private origin"}
            elif messages[-1]["content"] == "recall":
                name, args = "memory_get", {"memoryId": saved["id"]}
            else:
                yield ModelEvent("text", "acknowledged")
                return
            yield ModelEvent(
                "tool",
                {
                    "id": name + "-call",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                },
            )

    model = PausedRecall()
    runtime = Runtime(store, model, memory_model=ConversationModel())
    _, receipt, _ = await source(store, text="private origin")
    saved = await runtime.memory.save("alice", "private", "private origin", receipt["messageId"])
    target = await runtime.conversations.create("alice")
    await runtime.start()
    try:
        reply = await runtime.chat.submit("alice", target["id"], "recall", "recall")
        await asyncio.wait_for(model.started.wait(), 3)
        await runtime.memory.forget("alice", saved["id"])
        model.release.set()
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='failed'", (reply["turnId"],)
            ),
        )
        assert await runtime.tasks.list("alice") == []
        assert "private origin" not in json.dumps(
            (await runtime.context.project("alice", target["id"]))["messages"]
        )
    finally:
        await runtime.close()


async def test_forget_between_manifest_and_assistant_admission_is_rejected(store):
    runtime = Runtime(store, ConversationModel())
    c, receipt, _ = await source(store, text="private source")
    saved = await runtime.memory.save("alice", "private", "private source", receipt["messageId"])
    turn = await store.call(
        lambda db: dict(
            row(db, "SELECT * FROM turns WHERE id=?", (receipt["turnId"],)), owner_id="alice"
        )
    )
    plan = await runtime.context.project("alice", c["id"])
    await runtime.manifests.record(turn, 1, "fixture", "wire", plan, [], "main")
    await runtime.memory.forget("alice", saved["id"])
    with pytest.raises(DomainError, match="CONTEXT_SOURCE_FORGOTTEN"):
        await runtime.journal.start(turn)
    assert len((await runtime.conversations.messages("alice", c["id"]))["messages"]) == 1
    await runtime.close()
