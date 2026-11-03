"""Brief history distinguishes delivered replies from unanswered old requests."""

import json
from pathlib import Path

import pytest
from test_coordinator_handoff import call
from test_main_intent_scheduling import completed

from roami_agent.app import Runtime
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import rows

PREFIX = "Historical assistant reply (delivered, content omitted): "
CONTROLS = json.loads(
    (
        Path(__file__).resolve().parents[2] / "cases/case-109-mech-ar01/input/controls.json"
    ).read_text()
)


@pytest.mark.parametrize("mode", CONTROLS["reply_modes"])
async def test_old_delivered_reply_is_not_presented_as_an_unanswered_question(store, mode):
    captured, turns = [], []
    first, second, third = CONTROLS["requests"]

    class Main:
        model = "reply-history-fixture"

        async def stream(self, messages, tools):
            current = next(m["content"] for m in reversed(messages) if m["role"] == "user")
            if current == first:
                if mode == "text":
                    yield ModelEvent("text", "221")
                else:
                    yield ModelEvent(
                        "tool",
                        call("reply", {"text": "221", "mode": mode, "scopeQuote": first}),
                    )
            elif current == second:
                yield ModelEvent("text", '{"budget":800}')
            else:
                assert current == third
                captured.extend(messages)
                yield ModelEvent("text", '{"budget":800,"attendance":14}')

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        for index, text in enumerate([first, second, third]):
            receipt = await runtime.chat.submit("alice", conversation["id"], str(index), text)
            await completed(store, receipt["turnId"])
            turns.append(receipt["turnId"])
        marks = [(i, m) for i, m in enumerate(captured) if m["content"].startswith(PREFIX)]
        assert len(marks) == 1
        index, mark = marks[0]
        assert mark["role"] == "assistant"
        assert captured[index - 1] == {"role": "user", "content": first}
        assert "not proof of task completion" in mark["content"]
        assert "conversation_history" in mark["content"]
        assert "221" not in str(captured)
        assert {"role": "assistant", "content": '{"budget":800}'} in captured
        history = await runtime.conversations.messages("alice", conversation["id"])
        assert any(
            m["role"] == "assistant" and m["content"].get("text") == "221"
            for m in history["messages"]
        )
        assert not await runtime.tasks.list("alice")
        parts = json.loads(
            (
                await store.call(
                    lambda db: rows(
                        db, "SELECT parts_json FROM prompt_manifests WHERE turn_id=?", (turns[-1],)
                    )
                )
            )[0]["parts_json"]
        )
        delivered = await store.call(
            lambda db: rows(
                db,
                "SELECT message_id FROM events WHERE turn_id=? AND kind='message.completed'",
                (turns[0],),
            )
        )
        assert len(delivered) == 1
        assert delivered[0]["message_id"] in parts["sourceMessageIds"]
        assert parts["historyView"] == "main_briefing"
        assert parts["estimatedTokens"] >= parts["modelContext"]["historyTokens"] > 0
        if mode == "text":
            previous_parts = await store.call(
                lambda db: rows(
                    db, "SELECT parts_json FROM prompt_manifests WHERE turn_id=?", (turns[1],)
                )
            )
            assert json.loads(previous_parts[0]["parts_json"])["historyView"] == "full"
    finally:
        await runtime.close()


@pytest.mark.parametrize("wrong_scope", ["owner", "conversation"])
async def test_receipt_lookup_is_scoped_even_if_foreign_message_ids_are_supplied(
    store, wrong_scope
):
    from roami_agent.storage.reply_history import replied_message_ids

    class Main:
        model = "reply-history-owner-fixture"

        async def stream(self, messages, tools):
            yield ModelEvent("text", "Recorded answer.")

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "first", "First request.")
        await completed(store, receipt["turnId"])
        ids = await store.call(
            lambda db: [
                m["id"]
                for m in rows(db, "SELECT id FROM messages WHERE turn_id=?", (receipt["turnId"],))
            ]
        )
        binding = {"conversation_id": c["id"], "owner_id": "alice"}
        assert len(await store.call(lambda db: replied_message_ids(db, binding, ids))) == 1
        binding["owner_id" if wrong_scope == "owner" else "conversation_id"] = "foreign"
        assert await store.call(lambda db: replied_message_ids(db, binding, ids)) == []
    finally:
        await runtime.close()


@pytest.mark.parametrize("change", CONTROLS["excluded_records"])
async def test_nonanswers_and_excluded_sources_do_not_gain_delivery_receipts(store, change):
    captured = []

    class Main:
        model = "reply-history-exclusion-fixture"

        async def stream(self, messages, tools):
            if messages[-1]["content"] == "First request.":
                yield ModelEvent("text", "OLD_REPLY_VALUE")
            elif messages[-1]["content"] == "Second request.":
                yield ModelEvent("text", "LATEST_REPLY")
            else:
                captured.extend(messages)
                yield ModelEvent("text", "Current answer.")

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        first = await runtime.chat.submit("alice", c["id"], "first", "First request.")
        await completed(store, first["turnId"])
        second = await runtime.chat.submit("alice", c["id"], "second", "Second request.")
        await completed(store, second["turnId"])

        def alter(db):
            event = rows(
                db,
                "SELECT * FROM events WHERE turn_id=? AND kind='message.completed'",
                (first["turnId"],),
            )[0]
            user = rows(
                db, "SELECT id FROM messages WHERE turn_id=? AND role='user'", (first["turnId"],)
            )[0]["id"]
            if change == "missing_event":
                db.execute("DELETE FROM events WHERE id=?", (event["id"],))
            elif change == "task_report":
                db.execute(
                    "UPDATE events SET payload_json=json_set(payload_json,'$.source','task') WHERE id=?",
                    (event["id"],),
                )
            elif change == "question":
                db.execute(
                    "UPDATE messages SET content_json=json_set(content_json,'$.question',json('{}')) WHERE id=?",
                    (event["message_id"],),
                )
                db.execute(
                    "UPDATE events SET payload_json=json_set(payload_json,'$.question',json('{}')) WHERE id=?",
                    (event["id"],),
                )
            elif change == "failed_turn":
                db.execute("UPDATE turns SET state='failed' WHERE id=?", (first["turnId"],))
            else:
                mid = event["message_id"] if change.endswith("reply") else user
                if change.startswith("forgotten"):
                    db.execute(
                        "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'fixture',0)",
                        (mid,),
                    )
                else:
                    db.execute("UPDATE messages SET deleted_ms=1 WHERE id=?", (mid,))

        await store.call(alter, write=True)
        current = await runtime.chat.submit("alice", c["id"], "third", "Current request.")
        await completed(store, current["turnId"])
        assert not any(m["content"].startswith(PREFIX) for m in captured)
        assert "OLD_REPLY_VALUE" not in str(captured)
        assert "LATEST_REPLY" in str(captured)
    finally:
        await runtime.close()


async def test_explicit_history_read_restores_original_answer_without_receipt_substitution(store):
    captured = []
    read_rounds = 0

    class Main:
        model = "reply-history-restoration-fixture"

        async def stream(self, messages, tools):
            nonlocal read_rounds
            current = next(m["content"] for m in reversed(messages) if m["role"] == "user")
            if current == "First request.":
                yield ModelEvent("text", "OLDER_EXACT_VALUE")
            elif current == "Second request.":
                yield ModelEvent("text", "LATEST_REPLY")
            else:
                read_rounds += 1
                captured.append(messages)
                if read_rounds == 1:
                    yield ModelEvent("tool", call("conversation_history", {}))
                else:
                    yield ModelEvent("text", "OLDER_EXACT_VALUE")

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        for index, text in enumerate(
            ["First request.", "Second request.", "Quote the first answer."]
        ):
            receipt = await runtime.chat.submit("alice", c["id"], str(index), text)
            await completed(store, receipt["turnId"])
        assert read_rounds == 2
        assert any(m["content"].startswith(PREFIX) for m in captured[0])
        assert "OLDER_EXACT_VALUE" not in str(captured[0])
        assert not any(m["content"].startswith(PREFIX) for m in captured[1])
        assert {"role": "assistant", "content": "OLDER_EXACT_VALUE"} in captured[1]
    finally:
        await runtime.close()
