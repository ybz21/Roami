"""Brief initial context keeps constraints; explicit reads restore exact evidence."""

import json

import pytest
from test_coordinator_handoff import call
from test_main_intent_scheduling import completed

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import rows
from roami_agent.storage.task_request import task_user_request
from roami_agent.storage.transcript_repository import message


async def test_main_briefing_restores_old_records_without_losing_constraints_or_forgetting(store):
    rounds = 0

    class Main:
        model = "history-read"

        async def stream(self, messages, tools):
            nonlocal rounds
            rounds += 1
            text = str(messages)
            assert "Always preserve my source URLs" in text
            assert "LATEST_ANSWER" in text
            assert "FORGOTTEN_SECRET" not in text
            if rounds == 1:
                assert "EXACT_OLDER_DECISION" not in text
                assert messages[-1]["content"] == "Quote our earlier decision and explain it fully."
                yield ModelEvent("tool", call("conversation_history", {}))
            else:
                assert "EXACT_OLDER_DECISION" in text
                assert messages[-1]["role"] == "tool"
                yield ModelEvent("text", "EXACT_OLDER_DECISION")

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    c = await runtime.conversations.create("alice")

    def seed(db):
        for role, text in [
            ("user", "Always preserve my source URLs"),
            ("assistant", "EXACT_OLDER_DECISION " * 5000),
            ("assistant", "FORGOTTEN_SECRET"),
            ("assistant", "LATEST_ANSWER"),
        ]:
            mid = message(db, c["id"], c["active_branch_id"], role, {"text": text})
            if text == "FORGOTTEN_SECRET":
                db.execute(
                    "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'test',0)",
                    (mid,),
                )

    await store.call(seed, write=True)
    await runtime.start()
    try:
        receipt = await runtime.chat.submit(
            "alice", c["id"], "read-old", "Quote our earlier decision and explain it fully."
        )
        await completed(store, receipt["turnId"])
        manifests = await store.call(
            lambda db: rows(
                db,
                "SELECT parts_json FROM prompt_manifests WHERE turn_id=? ORDER BY attempt_no",
                (receipt["turnId"],),
            )
        )
        first, restored = [json.loads(m["parts_json"]) for m in manifests]
        assert first["historyView"] == "main_briefing"
        assert restored["historyView"] == "full"
        assert first["estimatedTokens"] < restored["estimatedTokens"] / 5
        assert first["requestBasis"] != restored["requestBasis"]
        assert restored["modelContext"]["usageTokens"] != first["estimatedTokens"]
        assert rounds == 2
        with pytest.raises(DomainError, match="CONVERSATION_NOT_FOUND"):
            await runtime.tools.registry["conversation_history"].handler(
                {}, {"owner": "mallory", "conversation": c["id"], "turnId": receipt["turnId"]}
            )
    finally:
        await runtime.close()


@pytest.mark.parametrize("legacy", [False, True])
async def test_agent_continuation_plans_are_not_promoted_to_user_constraints(store, legacy):
    from test_argument_repair_progress import claimed_turn

    runtime = Runtime(store, MainPlaceholder(), settings=Settings(workers=0))
    try:
        turn = await claimed_turn(runtime)
        task = await runtime.tasks.create(
            "alice", turn["conversation_id"], "Original lookup", key="lookup", record_intent=True
        )
        mid = await runtime.journal.start(turn)
        receipt = await runtime.gateway.invoke(
            turn,
            mid,
            call(
                "task_steer",
                {
                    "taskId": task["id"],
                    "revision": 1,
                    "text": "ASSISTANT_ONLY_STEP_BUDGET",
                    "requestComplete": True,
                },
            ),
            "main",
            {
                "owner": "alice",
                "conversation": turn["conversation_id"],
                "turnId": turn["id"],
                "toolCallId": "steer",
                "originMessageId": None,
            },
        )
        operation = receipt["operationId"]
        generated = await store.call(
            lambda db: rows(
                db,
                "SELECT * FROM messages WHERE json_extract(content_json,'$.operationId')=? AND role='user'",
                (operation,),
            )[0]
        )
        await store.call(
            lambda db: db.execute(
                "UPDATE messages SET content_json=json_set(content_json,'$.text','ASSISTANT_ONLY_STEP_BUDGET') WHERE id=?",
                (generated["id"],),
            ),
            write=True,
        )
        if legacy:
            await store.call(
                lambda db: db.execute(
                    "UPDATE messages SET content_json=json_remove(content_json,'$.sourceUserMessageId') WHERE id=?",
                    (generated["id"],),
                ),
                write=True,
            )
            generated = await store.call(
                lambda db: rows(db, "SELECT * FROM messages WHERE id=?", (generated["id"],))[0]
            )
        source = await store.call(lambda db: task_user_request(db, generated))
        assert "Perform the requested operations" in source["content_json"]
        assert source["id"] != generated["id"]
        snapshot = await runtime.conversations.messages("alice", turn["conversation_id"])
        assert source["id"] in {m["id"] for m in snapshot["messages"]}
        assert generated["id"] not in {m["id"] for m in snapshot["messages"]}
        configuration = runtime.loop.context._configuration(
            turn, runtime.settings.main_instructions, runtime.tools.catalog()
        )
        plan = await runtime.context.project(
            "alice", turn["conversation_id"], request_context=configuration
        )
        from roami_agent.context.main_history import main_history

        visible = main_history(plan, configuration)
        assert "ASSISTANT_ONLY_STEP_BUDGET" not in str(visible["messages"])
        assert "Perform the requested operations" in str(visible["messages"])
        assert "Earlier agent-issued task instructions" in str(plan["messages"])
    finally:
        await runtime.close()


class MainPlaceholder:
    model = "unused"

    async def stream(self, messages, tools):
        yield ModelEvent("text", "unused")
