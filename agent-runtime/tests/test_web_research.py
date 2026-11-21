"""Live questions route through native Browser Use, not a coding project or legacy session."""

import json
from unittest.mock import AsyncMock

import pytest
from mcp import types
from test_runtime import until

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


class MemoryModel:
    model = "memory-fixture"

    async def stream(self, messages, tools):
        yield ModelEvent("text", '{"memories":[]}')


@pytest.mark.parametrize(
    "target,executor",
    [
        ({"kind": "project", "projectId": "p", "resourceOnly": True}, "native"),
        ({"kind": "new_session", "directory": "/tmp", "resourceOnly": True}, "native"),
        ({"kind": "new_session", "resourceOnly": True}, "codex"),
    ],
)
async def test_resource_only_cannot_override_project_or_coding_workspace(store, target, executor):
    runtime = Runtime(store, MemoryModel())
    conversation = await runtime.conversations.create("alice")
    with pytest.raises(DomainError, match="INVALID_RESOURCE_ONLY_TARGET"):
        await runtime.tasks.create(
            "alice", conversation["id"], "lookup", key="bad", target=target, executor=executor
        )


async def test_disabled_browser_is_discovered_and_never_blindly_enqueued(store):
    runtime = Runtime(store, MemoryModel())
    overview = await runtime.tools.registry["capability_overview"].handler({}, {})
    assert overview["webResearchAvailable"] is False
    with pytest.raises(DomainError, match="WEB_RESEARCH_UNAVAILABLE"):
        await runtime.tools.registry["web_research"].handler({"goal": "latest quote"}, {})
    assert await store.call(lambda db: db.execute("SELECT count(*) FROM tasks").fetchone()[0]) == 0


async def test_lookup_uses_enabled_provider_tools_with_legacy_browser_config(store, tmp_path):
    config = tmp_path / "agent.toml"
    config.write_text(
        '[tools.browser]\nenabled=true\nendpoint="http://127.0.0.1:9222"\n'
        '[tools.mcp.external]\ncommand="fixture"\n'
    )
    settings = Settings.load(config)
    runtime = Runtime(store, MemoryModel(), settings=settings)
    try:
        assert "browser_open" not in runtime.tools.registry
        connection = runtime.mcp.connections["external"]
        session = AsyncMock()
        overview = runtime.tools.registry["capability_overview"].handler
        for remote, expected in [("search_contacts", False), ("browser_navigate", True)]:
            session.list_tools.return_value = types.ListToolsResult(
                tools=[types.Tool(name=remote, inputSchema={"type": "object"})]
            )
            await runtime.mcp._catalog(connection, session)
            assert (await overview({}, {}))["webResearchAvailable"] is expected
        runtime.tools.disabled_tools.update(connection.names)
        assert (await overview({}, {}))["webResearchAvailable"] is False
    finally:
        await runtime.close()


async def test_current_lookup_boundary_applies_to_custom_main_instructions_and_repeated_input(
    store,
):
    class Main:
        model = "custom-instruction-boundary"

        def __init__(self):
            self.prompts = []

        async def stream(self, messages, tools):
            self.prompts.append(messages)
            yield ModelEvent("text", "Fixture response")

    model = Main()
    runtime = Runtime(
        store,
        model,
        memory_model=MemoryModel(),
        settings=Settings(main_instructions="Custom coordinator instructions"),
    )
    try:
        conversation = await runtime.conversations.create("alice")
        await runtime.start()
        for key in ["first", "repeated"]:
            receipt = await runtime.chat.submit("alice", conversation["id"], key, "查看济南天气")
            await until(
                store,
                lambda db, turn_id=receipt["turnId"]: row(
                    db,
                    "SELECT id FROM turns WHERE id=? AND state='completed'",
                    (turn_id,),
                ),
            )
        assert len(model.prompts) == 2
        for prompt in model.prompts:
            assert prompt[0]["content"].startswith("Custom coordinator instructions")
            boundary = [
                m["content"]
                for m in prompt
                if m["role"] == "system" and m["content"].startswith("Current request boundary:")
            ]
            assert len(boundary) == 1
            assert "retrieval after this request" in boundary[0]
            assert "assistant-invented source restrictions" in boundary[0]
            assert "recap/status rather than a lookup" in boundary[0]
    finally:
        await runtime.close()


async def test_status_marks_old_research_as_cached_and_does_not_repeat_continuation_answers(store):
    from roami_agent.protocol.serialization import encoded

    runtime = Runtime(store, MemoryModel())
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            conversation["id"],
            "Public lookup",
            key="cached-lookup",
            target={"kind": "new_session", "resourceOnly": True},
            record_intent=True,
        )
        intent = json.loads(task["intent_json"])
        intent["continuation"] = {
            "state": "succeeded",
            "summary": "Old pricing table must not become a new lookup",
        }
        await store.call(
            lambda db: db.execute(
                "UPDATE tasks SET intent_json=? WHERE id=?", (encoded(intent), task["id"])
            ),
            write=True,
        )
        receipt = await runtime.conversations.accept(
            "alice", conversation["id"], "new-lookup", "查看济南天气"
        )
        snapshot = await runtime.tools.registry["task_status"].handler(
            {"taskId": task["id"]},
            {"owner": "alice", "conversation": conversation["id"], "turnId": receipt["turnId"]},
        )
        assert snapshot[0]["latestAttempt"]["retrievalEvidence"]["freshForCurrentRequest"] is False
        assert (
            "Do not poll status or steer it again"
            in snapshot[0]["latestAttempt"]["retrievalEvidence"]["recovery"]
        )
        await store.call(
            lambda db: db.execute("UPDATE tasks SET state='failed' WHERE id=?", (task["id"],)),
            write=True,
        )
        ended = await runtime.tools.registry["task_status"].handler(
            {"taskId": task["id"]},
            {"owner": "alice", "conversation": conversation["id"], "turnId": receipt["turnId"]},
        )
        assert "task_steer" in ended[0]["latestAttempt"]["retrievalEvidence"]["recovery"]
        assert "Old pricing table" not in json.dumps(snapshot)
        assert "Old pricing table" in json.dumps(await runtime.tasks.list("alice"))
    finally:
        await runtime.close()


@pytest.mark.parametrize("completion_report", [False, True])
async def test_current_evidence_and_completion_callbacks_never_request_another_lookup(
    store, completion_report
):
    from test_resource_leases import setup

    from roami_agent.protocol.serialization import encoded

    leases, lease, _, task_id, run_id = await setup(store)
    runtime = Runtime(store, MemoryModel())
    try:
        task = await store.call(lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (task_id,)))
        intent = json.loads(task["intent_json"])
        intent["target"] = {"kind": "new_session", "resourceOnly": True}
        await store.call(
            lambda db: db.execute(
                "UPDATE tasks SET intent_json=? WHERE id=?", (encoded(intent), task_id)
            ),
            write=True,
        )
        receipt = await runtime.conversations.accept(
            "alice", task["origin_conversation_id"], "current", "查看济南天气"
        )
        await leases.observe(
            "alice",
            lease["id"],
            task_id,
            run_id,
            lease["lease_epoch"],
            "b" * 64,
            {"url": "https://example.org/weather", "domText": "Current weather evidence"},
        )

        def ended(db):
            db.execute("UPDATE tasks SET state='failed' WHERE id=?", (task_id,))
            if completion_report:
                db.execute(
                    "UPDATE turns SET trigger_kind='completion' WHERE id=?", (receipt["turnId"],)
                )

        await store.call(ended, write=True)
        snapshot = await runtime.tools.registry["task_status"].handler(
            {"taskId": task_id},
            {
                "owner": "alice",
                "conversation": task["origin_conversation_id"],
                "turnId": receipt["turnId"],
            },
        )
        evidence = snapshot[0]["latestAttempt"]["retrievalEvidence"]
        assert evidence["freshForCurrentRequest"] is (None if completion_report else True)
        assert evidence["forCompletionReport"] is completion_report
        assert "continue this task with task_steer" not in evidence["recovery"]
        assert (
            "not a new lookup request" if completion_report else "Do not poll or rerun"
        ) in evidence["recovery"]
    finally:
        await runtime.close()
