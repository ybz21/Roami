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
        assert restored["historyView"] == "main_briefing"
        fixed_tokens = (
            first["modelContext"]["instructionTokens"] + first["modelContext"]["toolTokens"]
        )
        assert first["estimatedTokens"] < restored["estimatedTokens"]
        assert restored["estimatedTokens"] - fixed_tokens < 5000
        assert first["requestBasis"] == restored["requestBasis"]
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


async def test_task_result_read_does_not_restore_unrelated_main_history(store):
    from test_task_delivery_benchmark import mark

    task_id = None
    rounds = 0
    observed = []
    report = "CURRENT_TASK_RESULT_WITH_SOURCES " * 200

    class Main:
        model = "scoped-task-result"

        async def stream(self, messages, tools):
            nonlocal rounds
            rounds += 1
            text = str(messages)
            observed.append(
                {
                    "constraints": "Preserve literal source URLs" in text,
                    "latestReply": "LATEST_RELEVANT_REPLY" in text,
                    "forgotten": "FORGOTTEN_SECRET" in text,
                    "oldTool": "UNRELATED_OLD_TOOL_OUTPUT" in text,
                    "oldAnswer": "UNRELATED_OLD_ANSWER" in text,
                    "currentResult": report in text,
                }
            )
            if rounds == 1:
                yield ModelEvent(
                    "tool", call("task_status", {"taskId": task_id, "includeResult": True})
                )
            elif rounds == 2:
                observed[-1]["fullResult"] = (
                    json.loads(messages[-1]["content"])[0]["executorResult"]["summary"] == report
                )
                yield ModelEvent("tool", call("conversation_history", {}))
            else:
                yield ModelEvent("text", "Result and explicitly requested history are available.")

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    try:
        c = await runtime.conversations.create("alice")

        def seed(db):
            message(
                db, c["id"], c["active_branch_id"], "user", {"text": "Preserve literal source URLs"}
            )
            message(
                db,
                c["id"],
                c["active_branch_id"],
                "assistant",
                {"text": "", "tool_calls": [call("old_read", {}, "old-call")]},
            )
            message(
                db,
                c["id"],
                c["active_branch_id"],
                "tool",
                {"text": "UNRELATED_OLD_TOOL_OUTPUT " * 1000, "tool_call_id": "old-call"},
            )
            message(
                db,
                c["id"],
                c["active_branch_id"],
                "assistant",
                {"text": "UNRELATED_OLD_ANSWER " * 1000},
            )
            mid = message(
                db, c["id"], c["active_branch_id"], "assistant", {"text": "FORGOTTEN_SECRET"}
            )
            db.execute(
                "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'test',0)",
                (mid,),
            )
            message(
                db, c["id"], c["active_branch_id"], "assistant", {"text": "LATEST_RELEVANT_REPLY"}
            )

        await store.call(seed, write=True)
        task = await runtime.tasks.create(
            "alice", c["id"], "Existing analysis", key="analysis", record_intent=True
        )
        task_id = task["id"]
        await mark(runtime, task, "succeeded", {"state": "succeeded", "summary": report})
        await runtime.start()
        receipt = await runtime.chat.submit(
            "alice",
            c["id"],
            "details",
            "Read this task's full result, then explicitly check earlier history.",
        )
        await completed(store, receipt["turnId"])
        manifests = await store.call(
            lambda db: rows(
                db,
                "SELECT parts_json FROM prompt_manifests WHERE turn_id=? ORDER BY attempt_no",
                (receipt["turnId"],),
            )
        )
        initial, details, restored = [json.loads(m["parts_json"]) for m in manifests]
        assert all(o["constraints"] and o["latestReply"] and not o["forgotten"] for o in observed)
        assert observed[1]["fullResult"]
        assert not observed[1]["oldTool"] and not observed[1]["oldAnswer"]
        assert observed[2]["oldTool"] and observed[2]["oldAnswer"] and observed[2]["currentResult"]
        assert initial["historyView"] == details["historyView"] == "main_briefing"
        assert details["suppressedHistoryCount"] > 0
        assert restored["historyView"] == "main_briefing"
        assert details["estimatedTokens"] < restored["estimatedTokens"]
        assert rounds == 3
    finally:
        await runtime.close()
