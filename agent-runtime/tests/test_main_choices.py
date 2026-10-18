import json

import pytest
from test_runtime import until

from roami_agent.app import Runtime
from roami_agent.executors import targets
from roami_agent.protocol.models import ModelEvent
from roami_agent.storage.database import row


@pytest.mark.parametrize("executor", ["native", "codex", "claude"])
async def test_main_existing_session_delegate_sends_without_callbacks_or_confirmation(
    store, monkeypatch, executor
):
    calls = []

    async def execute(argv, **kwargs):
        calls.append(argv)
        if argv[1:3] == ["session", "resolve"]:
            return {
                "exitCode": 0,
                "stdout": json.dumps({"id": "stable-id", "label": "Legacy Codex"}),
            }
        assert argv[1:4] == ["agent", "execution", "send-message"]
        spec = json.loads(kwargs["input_data"])
        assert spec["sessionId"] == "stable-id" and spec["text"] == "Fix the layout"
        return {
            "exitCode": 0,
            "stdout": json.dumps(
                {"session": "stable-id", "state": "delivered", "outcomeKnown": True}
            ),
        }

    class Model:
        model = "existing-session-fixture"

        async def stream(self, messages, tools):
            if messages[-1]["role"] == "tool":
                yield ModelEvent("text", "Message delivered; completion is not tracked")
            else:
                yield ModelEvent(
                    "tool",
                    {
                        "id": "route",
                        "function": {
                            "name": "delegate",
                            "arguments": json.dumps(
                                {
                                    "goal": "Fix the layout",
                                    "executor": executor,
                                    "target": {"kind": "session", "sessionId": "Legacy Codex"},
                                }
                            ),
                        },
                    },
                )

    monkeypatch.setattr(targets, "execute", execute)
    runtime = Runtime(store, Model())
    try:
        await runtime.start()
        c = await runtime.conversations.create("alice")
        sent = await runtime.chat.submit(
            "alice", c["id"], "send", "Send the layout fix to Legacy Codex"
        )
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (sent["turnId"],)
            ),
        )
        assert len(calls) == 2
        assert (
            await store.call(lambda db: db.execute("SELECT count(*) FROM tasks").fetchone()[0]) == 0
        )
        view = await runtime.conversations.messages("alice", c["id"])
        assert view["activities"][0]["state"] == "delivered"
        assert view["activities"][0]["target"] == "stable-id"
    finally:
        await runtime.close()


async def test_question_is_a_durable_terminal_reply_and_selection_continues_chat(store):
    question = {
        "prompt": "Which session should receive this?",
        "options": [{"label": "Codex A", "description": "Recommended"}, {"label": "Codex B"}],
    }
    invocations = []

    class Model:
        model = "question-fixture"

        async def stream(self, messages, tools):
            invocations.append(messages[-1]["role"])
            if messages[-1]["content"] == "Codex A":
                yield ModelEvent("text", "Selected Codex A")
            else:
                yield ModelEvent(
                    "tool",
                    {
                        "id": "question",
                        "function": {"name": "ask_user", "arguments": json.dumps(question)},
                    },
                )

    runtime = Runtime(store, Model())
    try:
        await runtime.start()
        c = await runtime.conversations.create("alice")
        sent = await runtime.chat.submit("alice", c["id"], "question", "Send this to Codex")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (sent["turnId"],)
            ),
        )
        view = await runtime.conversations.messages("alice", c["id"])
        asked = next(m for m in view["messages"] if m["content"].get("question"))
        assert asked["content"]["question"] == question
        assert len(invocations) == 1
        events = await runtime.conversations.events("alice", c["id"])
        assert (
            next(e for e in events if e["kind"] == "message.completed")["payload"]["question"]
            == question
        )
        answer = await runtime.chat.submit("alice", c["id"], "answer", "Codex A")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (answer["turnId"],)
            ),
        )
        view = await runtime.conversations.messages("alice", c["id"])
        assert view["messages"][-1]["content"]["text"] == "Selected Codex A"
    finally:
        await runtime.close()
