"""Brief history preserves accepted work beside the request it handled."""

import json
from pathlib import Path

import pytest
from test_coordinator_handoff import call
from test_main_intent_scheduling import completed

from roami_agent.app import Runtime
from roami_agent.protocol.models import ModelEvent
from roami_agent.protocol.serialization import encoded
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import rows
from roami_agent.tools.command_families import COMMANDS

CONTROLS = json.loads(
    (
        Path(__file__).resolve().parents[2] / "cases/case-107-mech-hr01/input/controls.json"
    ).read_text()
)


def command(name, arguments, cli):
    if cli and name != "delegate":
        return call("bash", {"argv": ["roami", *COMMANDS[name], "--input", json.dumps(arguments)]})
    return call(name, arguments)


@pytest.mark.parametrize(
    "continued,cli", [(p["continued"], p["cli"]) for p in CONTROLS["handoffs"]]
)
async def test_handoff_receipts_stay_with_their_requests_without_executor_briefs(
    store, cli, continued
):
    captured = []
    first = CONTROLS["first_request"]
    update = CONTROLS["update_request"]
    current = CONTROLS["current_request"]
    private_brief = CONTROLS["executor_detail"] * 200

    class Main:
        model = "handoff-history-fixture"

        async def stream(self, messages, tools):
            user = next(m["content"] for m in reversed(messages) if m["role"] == "user")
            if user == first:
                yield ModelEvent(
                    "tool",
                    command(
                        "delegate",
                        {"goal": first + private_brief, "requestComplete": True},
                        cli,
                    ),
                )
            elif user == update:
                task = (await runtime.tasks.list("alice"))[0]
                yield ModelEvent(
                    "tool",
                    command(
                        "task_steer",
                        {
                            "taskId": task["id"],
                            "revision": task["revision"],
                            "text": update + private_brief,
                            "sourceQuote": update,
                            "requestComplete": True,
                        },
                        cli,
                    ),
                )
            else:
                assert user == current
                captured.extend(messages)
                yield ModelEvent("text", "The separate request is ready to handle.")

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        cid = conversation["id"]
        requests = [first, *([update] if continued else []), current]
        for index, text in enumerate(requests):
            receipt = await runtime.chat.submit("alice", cid, str(index), text)
            await completed(store, receipt["turnId"])
        task = (await runtime.tasks.list("alice"))[0]
        receipts = [
            (index, json.loads(m["content"].split(": ", 1)[1]))
            for index, m in enumerate(captured)
            if m["role"] == "assistant" and m["content"].startswith("Historical task handoff (")
        ]
        assert len(receipts) == (2 if continued else 1)
        for (index, handoff), text, operation in zip(
            receipts, requests[:-1], ["delegate", "task_steer"][: len(receipts)], strict=True
        ):
            source_index = next(
                i for i, m in enumerate(captured) if m["role"] == "user" and m["content"] == text
            )
            assert source_index < index < len(captured) - 1
            assert handoff["operation"] == operation
            assert handoff["taskId"] == task["id"]
            assert handoff["acceptedOnly"] is True and handoff["requestComplete"] is True
            assert "state" not in handoff
            assert "not completion or new authorization" in captured[index]["content"]
        assert private_brief not in str(captured)
        history = await runtime.conversations.messages("alice", cid)
        assert private_brief in str(history)
        manifests = await store.call(
            lambda db: rows(
                db, "SELECT parts_json FROM prompt_manifests WHERE turn_id=?", (receipt["turnId"],)
            )
        )
        parts = json.loads(manifests[0]["parts_json"])
        original_receipts = await store.call(
            lambda db: rows(
                db,
                "SELECT result_message_id FROM tool_calls WHERE tool_name IN ('delegate','task_steer') AND state='succeeded'",
            )
        )
        assert {r["result_message_id"] for r in original_receipts} <= set(parts["sourceMessageIds"])
        assert len(await runtime.tasks.list("alice")) == 1
    finally:
        await runtime.close()


@pytest.mark.parametrize("change", CONTROLS["excluded_receipts"])
async def test_brief_history_does_not_promote_unconfirmed_or_excluded_receipts(store, change):
    captured = []

    class Main:
        model = "handoff-provenance-fixture"

        async def stream(self, messages, tools):
            if messages[-1]["content"] == "Create the original report.":
                yield ModelEvent(
                    "tool", call("delegate", {"goal": "Original report", "requestComplete": True})
                )
            else:
                captured.extend(messages)
                yield ModelEvent("text", "Handle the current request.")

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    await runtime.start()
    try:
        owner = "bob" if change == "foreign_owner" else "alice"
        first = await runtime.conversations.create(owner)
        receipt = await runtime.chat.submit(
            owner, first["id"], "first", "Create the original report."
        )
        await completed(store, receipt["turnId"])
        task = (await runtime.tasks.list(owner))[0]

        def alter(db):
            result = rows(db, "SELECT * FROM tool_calls WHERE turn_id=?", (receipt["turnId"],))[0]
            if change in {"failed", "unknown"}:
                db.execute("UPDATE tool_calls SET state=? WHERE id=?", (change, result["id"]))
            elif change == "foreign_tool":
                db.execute(
                    "UPDATE tool_calls SET tool_name='memory_search' WHERE id=?", (result["id"],)
                )
            elif change == "unbound_result":
                db.execute(
                    "UPDATE tool_calls SET result_message_id=NULL WHERE id=?", (result["id"],)
                )
            elif change == "rejected":
                db.execute(
                    "UPDATE messages SET content_json=json_set(content_json,'$.text',?) WHERE id=?",
                    (
                        encoded({"taskId": task["id"], "acceptedOnly": False}),
                        result["result_message_id"],
                    ),
                )
            elif change in {"forget_request", "forget_receipt"}:
                mid = (
                    task["origin_message_id"]
                    if change == "forget_request"
                    else result["result_message_id"]
                )
                db.execute(
                    "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES(?,?,'fixture',0)",
                    (owner, mid),
                )
            elif change == "delete_request":
                db.execute(
                    "UPDATE messages SET deleted_ms=1 WHERE id=?", (task["origin_message_id"],)
                )

        await store.call(alter, write=True)
        conversation = (
            await runtime.conversations.create("alice") if change == "foreign_owner" else first
        )
        next_receipt = await runtime.chat.submit(
            "alice", conversation["id"], "next", "A separate request."
        )
        await completed(store, next_receipt["turnId"])
        assert not any(
            m["role"] == "assistant" and m["content"].startswith("Historical task handoff (")
            for m in captured
        )
        if change in {"forget_request", "delete_request", "foreign_owner"}:
            assert task["id"] not in str(captured)
    finally:
        await runtime.close()


async def test_multiple_handoffs_preserve_partial_request_coverage(store):
    captured = []

    class Main:
        model = "partial-handoff-fixture"

        async def stream(self, messages, tools):
            if messages[-1]["content"] == "Create two independent reports.":
                yield ModelEvent(
                    "tool",
                    call("delegate", {"goal": "First report", "requestComplete": False}, "first"),
                )
                yield ModelEvent(
                    "tool",
                    call("delegate", {"goal": "Second report", "requestComplete": True}, "second"),
                )
            else:
                captured.extend(messages)
                yield ModelEvent("text", "Ready for the new request.")

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        for index, text in enumerate(["Create two independent reports.", "A separate request."]):
            receipt = await runtime.chat.submit("alice", conversation["id"], str(index), text)
            await completed(store, receipt["turnId"])
        handoffs = [
            json.loads(m["content"].split(": ", 1)[1])
            for m in captured
            if m["role"] == "assistant" and m["content"].startswith("Historical task handoff (")
        ]
        assert [h["requestComplete"] for h in handoffs] == [False, True]
        assert {h["taskId"] for h in handoffs} == {
            t["id"] for t in await runtime.tasks.list("alice")
        }
        assert all(h["acceptedOnly"] is True and "state" not in h for h in handoffs)
    finally:
        await runtime.close()


async def test_explicit_history_read_restores_original_handoff_protocol(store):
    rounds = 0

    class Main:
        model = "handoff-history-read-fixture"

        async def stream(self, messages, tools):
            nonlocal rounds
            rounds += 1
            if rounds == 1:
                yield ModelEvent(
                    "tool",
                    call("delegate", {"goal": "FULL_EXECUTOR_BRIEF", "requestComplete": True}),
                )
            elif rounds == 2:
                assert "Historical task handoff (" in str(messages)
                assert "FULL_EXECUTOR_BRIEF" not in str(messages)
                yield ModelEvent("tool", call("conversation_history", {}))
            else:
                assert rounds == 3
                assert "FULL_EXECUTOR_BRIEF" in str(messages)
                assert "Historical task handoff (" not in str(messages)
                assert any(m.get("tool_calls") for m in messages)
                assert any(m["role"] == "tool" and "acceptedOnly" in m["content"] for m in messages)
                yield ModelEvent("text", "The original receipt is available.")

    runtime = Runtime(store, Main(), settings=Settings(workers=0))
    await runtime.start()
    try:
        conversation = await runtime.conversations.create("alice")
        for index, text in enumerate(["Create a report.", "Read the original task instructions."]):
            receipt = await runtime.chat.submit("alice", conversation["id"], str(index), text)
            await completed(store, receipt["turnId"])
        assert rounds == 3
    finally:
        await runtime.close()
