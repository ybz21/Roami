"""Real Go CLI continuation and lifecycle receipts, without contacting a coding provider."""

import asyncio
import json
import os
import sys
from pathlib import Path

from roami_agent.app import Runtime
from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.tasks import Tasks
from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import Database, row
from roami_agent.tools.process import execute


class CompletionModel:
    model = "injected-completion-model"

    async def stream(self, messages, tools):
        yield ModelEvent("text", "The existing session returned evidence; acceptance is pending.")


async def main():
    binary, root, session_id, *options = sys.argv[1:]
    provider = options[0] if options else "codex"
    assert provider in {"codex", "claude"}
    prompt_id_field = "prompt_id" if provider == "claude" else "turn_id"
    root = Path(root)
    database = Database(root / "python/database/agents/runtime.db", root / "python", managed=False)
    await database.open()
    settings = Settings(cli_bin=binary)
    executor = CodingExecutor(database, settings)
    conversations = Conversations(database)
    tasks = Tasks(database, conversations)
    conversation = await conversations.create("local")
    task = await tasks.create(
        "local",
        conversation["id"],
        "Continue the existing session and provide evidence",
        key="continue-once",
        executor=provider,
        target={"kind": "session", "sessionId": session_id},
        record_intent=True,
    )
    attempt = await database.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )

    def preparing(db):
        db.execute("UPDATE tasks SET state='preparing' WHERE id=?", (task["id"],))
        db.execute("UPDATE task_attempts SET state='starting' WHERE id=?", (attempt["id"],))
        db.execute("UPDATE jobs SET state='done' WHERE aggregate_id=?", (task["id"],))

    await database.call(preparing, write=True)
    assert await executor.run(task, attempt) is None
    prompt = (root / "prompt").read_text()
    from roami_agent.replies.delivery_policy import DELIVERY_INSTRUCTIONS

    assert DELIVERY_INSTRUCTIONS in prompt
    assert prompt.endswith(json.loads(task["intent_json"])["goal"])

    async def event(payload, *, notification=False):
        response = await execute(
            [binary, "agent", "execution", "event", "--executor", provider]
            + (["--notification", json.dumps(payload)] if notification else ["--file", "-"]),
            input_data=None if notification else json.dumps(payload).encode(),
            env=dict(os.environ, TMUX_PANE="%3"),
        )
        assert response["exitCode"] == 0, response["stderr"]
        assert json.loads(response["stdout"]) == {}

    await event(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "provider-thread",
            prompt_id_field: "continuation-turn",
            "prompt": prompt,
        }
    )
    await executor.poll(tasks)
    current = (await tasks.list("local"))[0]
    assert current["state"] == "running"
    assert current["latestAttempt"]["sessionId"] == session_id
    assert current["latestAttempt"]["agentConversationId"] == "provider-thread"
    await event(
        {
            "hook_event_name": "Stop",
            "session_id": "provider-thread",
            prompt_id_field: "continuation-turn",
            "background_tasks": [],
            "session_crons": [],
            "last_assistant_message": "Evidence from the original coding session",
        }
    )
    await executor.poll(tasks)
    assert (await tasks.list("local"))[0]["state"] == "running"
    completion = {
        "type": "agent-turn-complete",
        "thread-id": "provider-thread",
        "turn-id": "continuation-turn",
        "input-messages": [prompt],
        "last-assistant-message": "Evidence from the original coding session",
    }
    if provider == "claude":
        completion = {
            "hook_event_name": "Notification",
            "notification_type": "idle_prompt",
            "session_id": "provider-thread",
            "prompt_id": "continuation-turn",
        }
    await event(completion, notification=provider == "codex")
    await event(completion, notification=provider == "codex")
    await executor.poll(tasks)
    await executor.poll(tasks)
    assert (await tasks.list("local"))[0]["state"] == "verifying"
    events = await conversations.events("local", conversation["id"])
    assert sum(item["kind"] == "task.result" for item in events) == 1
    assert (root / "submits").read_text().count("submitted") == 1

    runtime = Runtime(database, CompletionModel(), settings=settings, executor=executor)
    await runtime.start()
    try:
        async with asyncio.timeout(10):
            while True:
                view = await conversations.messages("local", conversation["id"])
                if any(message["role"] == "assistant" for message in view["messages"]):
                    break
                await asyncio.sleep(0.02)
        assert (await tasks.list("local"))[0]["state"] == "waiting_user"
        assert (root / "submits").read_text().count("submitted") == 1
        print(
            f"session continuation scenario passed: {provider}, durable binding, observed completion, original conversation, no replay"
        )
    finally:
        await runtime.close()
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
