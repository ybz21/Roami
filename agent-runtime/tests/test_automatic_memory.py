import json

import pytest
from test_runtime import ConversationModel, until

from roami_agent.app import Runtime
from roami_agent.context.prompt_builder import PromptBuilder
from roami_agent.conversation.transcript import Conversations
from roami_agent.memory.intake import direct_user_preference
from roami_agent.memory.records import Memories
from roami_agent.observability.prompt_manifests import PromptManifests
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.memory import MemoryProposal
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row, rows


async def test_remember_request_persists_before_reply_and_is_idempotent(store):
    conversations = Conversations(store)
    c = await conversations.create("alice")
    text = "帮我记下，以后优先用codex创建任务"
    first = await conversations.accept("alice", c["id"], "remember", text)
    again = await conversations.accept("alice", c["id"], "remember", text)
    memory = Memories(store)
    hits = await memory.search("alice", "codex", conversation_id=c["id"])
    assert len(hits) == 1 and hits[0]["state"] == "active"
    assert hits[0]["body"] == "以后优先用codex创建任务"
    assert hits[0]["sourceRefs"][0]["message_id"] == first["messageId"]
    assert again["messageId"] == first["messageId"] and again["reused"]
    assert not await memory.search("bob", "codex")
    await memory.delete("alice", hits[0]["id"])
    await conversations.accept("alice", c["id"], "remember", text)
    assert not await memory.search("alice", "codex")


@pytest.mark.parametrize(
    "text",
    [
        "你还记得 codex 吗？",
        "请不要记住这个",
        "记住了吗？",
        "例如：“记住优先用codex”",
        "Remember that?",
        "帮我记下？",
    ],
)
async def test_questions_negations_and_examples_do_not_activate(store, text):
    conversations = Conversations(store)
    c = await conversations.create("alice")
    await conversations.accept("alice", c["id"], "one", text)
    assert not await Memories(store).search("alice")


def test_proposal_requires_verbatim_user_source_not_assistant_or_fabrication():
    args = {
        "title": "执行器偏好",
        "body": "以后优先用 Codex",
        "kind": "preference",
        "sourceIds": ["user"],
        "evidenceQuote": "以后优先用 Codex",
    }
    source = {
        "id": "user",
        "role": "user",
        "content_json": json.dumps({"text": "以后优先用 Codex"}),
    }
    assert direct_user_preference(MemoryProposal(**args), [source])
    assert not direct_user_preference(MemoryProposal(**args), [dict(source, role="assistant")])
    assert not direct_user_preference(MemoryProposal(**dict(args, body="以后用 Claude")), [source])
    assert not direct_user_preference(MemoryProposal(**dict(args, evidenceQuote=None)), [source])


class DirectPreferenceModel:
    model = "direct-user-preference-fixture"

    async def stream(self, messages, tools):
        sources = json.loads(messages[-1]["content"])
        source = next(source for source in sources if source["role"] == "user")
        quote = json.loads(source["content"])["text"]
        yield ModelEvent(
            "text",
            json.dumps(
                {
                    "memories": [
                        {
                            "title": "任务执行器偏好",
                            "body": quote,
                            "kind": "preference",
                            "sourceIds": [source["id"]],
                            "evidenceQuote": quote,
                        }
                    ]
                }
            ),
        )


async def test_automatic_extraction_and_recall_without_memory_tool_call(store):
    runtime = Runtime(store, ConversationModel(), memory_model=DirectPreferenceModel())
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        await runtime.chat.submit("alice", c["id"], "preference", "以后优先用 Codex 创建任务")
        await until(
            store,
            lambda db: row(
                db, "SELECT * FROM memory_records WHERE state='active' AND kind='preference'"
            ),
        )
        memory = await store.call(
            lambda db: row(
                db, "SELECT * FROM memory_records WHERE state='active' AND kind='preference'"
            )
        )
        assert memory["body"] == "以后优先用 Codex 创建任务"
        receipt = await runtime.conversations.accept("alice", c["id"], "next", "开始处理下一个需求")
        turn = await store.call(
            lambda db: row(db, "SELECT * FROM turns WHERE id=?", (receipt["turnId"],))
        )
        turn["owner_id"] = "alice"
        builder = PromptBuilder(store, runtime.context, runtime.settings, memory=runtime.memory)
        plan, prompt = await builder.build(turn, "", [], None)
        assert any(
            "Automatically recalled" in item.get("content", "") and "Codex" in item["content"]
            for item in prompt
        )
        assert plan["memoryEvidence"] == [
            {"memoryId": memory["id"], "revision": memory["revision"]}
        ]
        assert not await store.call(
            lambda db: row(
                db, "SELECT id FROM tool_calls WHERE tool_name IN ('memory_get','memory_search')"
            )
        )
        await PromptManifests(store).record(turn, 1, "fixture", "hash", plan, [], "main")
        await store.call(lambda db: assert_context_admitted(db, turn))
        await runtime.memory.delete("alice", memory["id"])
        with pytest.raises(DomainError, match="CONTEXT_SOURCE_FORGOTTEN"):
            await store.call(lambda db: assert_context_admitted(db, turn))
        _, prompt = await builder.build(turn, "", [], None)
        assert not any("Automatically recalled" in item.get("content", "") for item in prompt)
    finally:
        await runtime.close()


async def test_forget_traces_automatically_recalled_memories(store):
    runtime = Runtime(store, ConversationModel())
    c = await runtime.conversations.create("alice")
    await runtime.conversations.accept("alice", c["id"], "remember", "记住，以后优先用 Codex")
    memory = (await runtime.memory.search("alice", "Codex"))[0]
    await runtime.start()
    try:
        receipt = await runtime.chat.submit("alice", c["id"], "next", "处理下一件事")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
        )
        await runtime.memory.forget("alice", memory["id"])
        omitted = await store.call(
            lambda db: rows(
                db,
                "SELECT o.message_id FROM context_omissions o JOIN messages m ON m.id=o.message_id WHERE m.turn_id=?",
                (receipt["turnId"],),
            )
        )
        assert omitted
        plan = await runtime.context.project("alice", c["id"])
        assert not any(
            "Automatically recalled" in item.get("content", "") for item in plan["messages"]
        )
    finally:
        await runtime.close()


async def test_late_automatic_preference_cannot_override_newer_user_source(store):
    from roami_agent.memory.writer import commit_memory

    conversations = Conversations(store)
    c = await conversations.create("alice")
    old = await conversations.accept("alice", c["id"], "old", "优先用 Claude")
    new = await conversations.accept("alice", c["id"], "new", "改成优先用 Codex")

    def write(db):
        db.execute("UPDATE messages SET created_ms=1 WHERE id=?", (old["messageId"],))
        db.execute("UPDATE messages SET created_ms=2 WHERE id=?", (new["messageId"],))
        current = commit_memory(
            db,
            "alice",
            "任务执行器",
            "优先用 Codex",
            [new["messageId"]],
            kind="preference",
            conversation_id=c["id"],
            confirmed=True,
        )
        late = commit_memory(
            db,
            "alice",
            "任务执行器",
            "优先用 Claude",
            [old["messageId"]],
            kind="preference",
            conversation_id=c["id"],
            confirmed=True,
            automatic=True,
        )
        return current, late

    current, late = await store.call(write, write=True)
    assert late["state"] == "conflict"
    assert (await Memories(store).get("alice", current["id"]))["body"] == "优先用 Codex"


class UserScopePreferenceModel:
    model = "user-scope-preference-fixture"

    def __init__(self, scope="user_preference", direct=True):
        self.scope, self.direct = scope, direct

    async def stream(self, messages, tools):
        source = next(
            item for item in json.loads(messages[-1]["content"]) if item["role"] == "user"
        )
        quote = json.loads(source["content"])["text"]
        yield ModelEvent(
            "text",
            json.dumps(
                {
                    "memories": [
                        {
                            "title": "用户报告偏好",
                            "body": quote,
                            "kind": "preference",
                            "sourceIds": [source["id"]],
                            "proposedScope": self.scope,
                            **({"evidenceQuote": quote} if self.direct else {}),
                        }
                    ]
                }
            ),
        )


@pytest.mark.parametrize(
    "proposed_scope,direct",
    [("source", True), ("user_preference", True), ("user_preference", False)],
)
async def test_personal_preference_scope_requires_direct_source_and_forgetting_invalidates_promotion(
    store, proposed_scope, direct
):
    runtime = Runtime(
        store, ConversationModel(), memory_model=UserScopePreferenceModel(proposed_scope, direct)
    )
    await runtime.start()
    try:
        first = await runtime.conversations.create("alice")
        await runtime.chat.submit(
            "alice",
            first["id"],
            "remember-personal",
            "帮我记住：我的报告偏好编号是 oak-8372，默认简洁。",
        )
        await until(
            store,
            lambda db: row(db, "SELECT id FROM jobs WHERE kind='memory.extract' AND state='done'"),
        )
        records = await store.call(
            lambda db: rows(
                db,
                "SELECT * FROM memory_records WHERE owner_id='alice' AND conversation_id IS NULL AND state='active'",
            )
        )
        assert bool(records) is (proposed_scope == "user_preference" and direct)
        second = await runtime.conversations.create("alice")
        receipt = await runtime.conversations.accept(
            "alice", second["id"], "recall", "沿用我的报告偏好"
        )
        turn = await store.call(
            lambda db: row(db, "SELECT * FROM turns WHERE id=?", (receipt["turnId"],))
        )
        turn["owner_id"] = "alice"
        builder = PromptBuilder(store, runtime.context, runtime.settings, memory=runtime.memory)
        plan, prompt = await builder.build(turn, "", [], None)
        assert bool(plan["memoryEvidence"]) is bool(records)
        if records:
            assert "oak-8372" in json.dumps(prompt)
            assert not await runtime.memory.search("bob", "oak-8372")
            local = await store.call(
                lambda db: row(
                    db,
                    "SELECT id FROM memory_records WHERE conversation_id=? AND state='active' ORDER BY created_ms LIMIT 1",
                    (first["id"],),
                )
            )
            await runtime.memory.delete("alice", local["id"])
            plan, _ = await builder.build(turn, "", [], None)
            assert not plan["memoryEvidence"]
    finally:
        await runtime.close()


async def test_task_preference_cannot_be_promoted_to_user_scope(store):
    runtime = Runtime(store, ConversationModel(), memory_model=UserScopePreferenceModel())
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            conversation["id"],
            "这个任务的报告用 local-scope-4821 格式",
            key="scoped-preference",
            record_intent=True,
        )
        await until(
            store,
            lambda db: row(
                db,
                "SELECT id FROM memory_records WHERE task_id=? AND state='active'",
                (task["id"],),
            ),
        )
        assert not await store.call(
            lambda db: row(
                db, "SELECT id FROM memory_records WHERE conversation_id IS NULL AND state='active'"
            )
        )
    finally:
        await runtime.close()


async def test_forgetting_user_preference_excludes_other_records_of_original_source(store):
    runtime = Runtime(store, ConversationModel(), memory_model=UserScopePreferenceModel())
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        await runtime.chat.submit(
            "alice", conversation["id"], "personal-source", "记住：我的偏好编号是 pine-3571"
        )
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM memory_records WHERE conversation_id IS NULL AND state='active'"
            ),
        )
        records = await runtime.memory.search("alice", "pine-3571")
        global_record = next(item for item in records if item["conversation_id"] is None)
        local_record = next(item for item in records if item["conversation_id"] is not None)
        await runtime.memory.forget("alice", global_record["id"])
        assert not await runtime.memory.search("alice", "pine-3571")
        with pytest.raises(DomainError, match="MEMORY_SOURCE_NOT_FOUND"):
            await runtime.memory.get("alice", local_record["id"])
    finally:
        await runtime.close()
