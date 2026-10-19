import json

from test_runtime import until

from roami_agent.app import Runtime
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


async def test_main_continues_past_legacy_step_limit(store):
    class Model:
        model = "long-tool-chain"
        calls = 0

        async def stream(self, messages, tools):
            self.calls += 1
            if self.calls <= 20:
                yield ModelEvent(
                    "tool",
                    {
                        "id": f"list-{self.calls}",
                        "function": {"name": "tool_list", "arguments": "{}"},
                    },
                )
            else:
                yield ModelEvent("text", "Completed twenty tool calls")

    model = Model()
    runtime = Runtime(store, model, settings=Settings(max_steps=1))
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit(
            "alice", c["id"], "long", "Inspect available capabilities"
        )
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
            timeout=15,
        )
        assert model.calls == 21
        assert (await runtime.conversations.messages("alice", c["id"]))["messages"][-1]["content"][
            "text"
        ] == "Completed twenty tool calls"
    finally:
        await runtime.close()


async def test_unlimited_task_accounting_and_explicit_cancellation(store):
    from test_routing_policy import setup
    from test_task_delivery_benchmark import admit

    from roami_agent.dispatch.runner import TaskDispatcher

    runtime, _, _, _, binding = await setup(store)
    try:
        task = await admit(runtime, binding, "Long task", "long")
        dispatcher = TaskDispatcher(store, runtime.tasks, None, None, None, None, {})
        for _ in range(25):
            await dispatcher.charge_budget(task["id"])
        current = await store.call(
            lambda db: row(db, "SELECT budget_json FROM tasks WHERE id=?", (task["id"],))
        )
        assert json.loads(current["budget_json"])["usedSteps"] == 25
        await runtime.tasks.cancel("alice", task["id"])
        assert (await runtime.tasks.get("alice", task["id"]))["task"]["state"] in {
            "cancelled",
            "cancelling",
        }
    finally:
        await runtime.close()


async def test_notification_history_survives_read_cursor(store):
    from test_runtime import ConversationModel

    runtime = Runtime(store, ConversationModel())
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        receipt = await runtime.chat.submit("alice", c["id"], "hello", "hello")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM turns WHERE id=? AND state='completed'", (receipt["turnId"],)
            ),
        )
        notices = await runtime.notifications.list("alice")
        assert notices and not notices[0]["read"]
        await runtime.notifications.mark_read("alice", c["id"], notices[0]["id"])
        assert await runtime.notifications.list("alice") == []
        assert (await runtime.notifications.list("alice", include_read=True))[0]["read"]
        assert await runtime.notifications.list("other", include_read=True) == []
    finally:
        await runtime.close()
