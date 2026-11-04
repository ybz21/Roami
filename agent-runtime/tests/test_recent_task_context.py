from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.storage.database import row
from roami_agent.storage.task_context import recent_task_context


async def test_recent_tasks_preserve_identity_and_exclude_foreign_forgotten_and_future_work(store):
    runtime = Runtime(store, ConversationModel())
    try:
        conversation = await runtime.conversations.create("alice")
        visible = await runtime.tasks.create(
            "alice", conversation["id"], "Original work", key="visible", record_intent=True
        )
        forgotten = await runtime.tasks.create(
            "alice", conversation["id"], "Forgotten work", key="forgotten", record_intent=True
        )
        future = await runtime.tasks.create(
            "alice", conversation["id"], "Later request", key="future", record_intent=True
        )
        other = await runtime.conversations.create("bob")
        await runtime.tasks.create(
            "bob", other["id"], "Private work", key="foreign", record_intent=True
        )
        receipt = await runtime.conversations.accept(
            "alice", conversation["id"], "continue", "Continue original work"
        )
        turn = await store.call(
            lambda db: row(db, "SELECT * FROM turns WHERE id=?", (receipt["turnId"],))
        )
        turn["owner_id"] = "alice"

        def exclude(db):
            db.execute(
                "UPDATE tasks SET created_ms=? WHERE id=?", (turn["created_ms"] + 1, future["id"])
            )
            db.execute(
                "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES(?,?,'forgotten_memory_source',?)",
                ("alice", forgotten["origin_message_id"], turn["created_ms"]),
            )

        await store.call(exclude, write=True)
        result = await store.call(lambda db: recent_task_context(db, turn))
        assert len(result) == 1
        assert result[0]["taskId"] == visible["id"] and result[0]["revision"] == 1
        assert result[0]["goal"] == "Original work" and result[0]["executor"] == "native"
    finally:
        await runtime.close()


async def test_tasks_from_one_request_keep_individual_titles_and_full_user_source(store):
    runtime = Runtime(store, ConversationModel())
    try:
        conversation = await runtime.conversations.create("alice")
        source = "Create separate reports for north and south; do not send either report."
        request = await runtime.conversations.accept("alice", conversation["id"], "reports", source)
        message = await store.call(
            lambda db: row(
                db, "SELECT id FROM messages WHERE turn_id=? AND role='user'", (request["turnId"],)
            )
        )
        goals = {}
        for region in ("north", "south"):
            goal = f"Prepare the {region} report"
            task = await runtime.tasks.create(
                "alice",
                conversation["id"],
                goal + "\n" + "EXECUTOR_ONLY_DETAIL " * 200,
                key=region,
                origin_message_id=message["id"],
            )
            goals[task["id"]] = goal
        followup = await runtime.conversations.accept(
            "alice", conversation["id"], "followup", "Add a chart to the north report only."
        )
        turn = await store.call(
            lambda db: row(db, "SELECT * FROM turns WHERE id=?", (followup["turnId"],))
        )
        result = await store.call(lambda db: recent_task_context(db, dict(turn, owner_id="alice")))
        assert {task["taskId"]: task["title"] for task in result} == goals
        assert all(task["goal"] == source for task in result)
        assert all(task["sourceMessageId"] == message["id"] for task in result)
        assert "EXECUTOR_ONLY_DETAIL" not in str(result)
    finally:
        await runtime.close()
