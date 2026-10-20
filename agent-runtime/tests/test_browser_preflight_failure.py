"""A failed browser readiness check cannot start actions or feed another retry loop."""

import json

import pytest
from test_argument_repair_progress import claimed_turn
from test_tool_rejection_progress import Calls

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row

CAPS = {
    "browserId": "fixture-browser",
    "features": ["target_id", "operation_receipts", "scene_observation", "expected_scene"],
}


@pytest.mark.parametrize(
    "result,code",
    [
        (
            {"exitCode": 1, "stdout": "", "stderr": "Connection refused"},
            "BROWSER_DRIVER_UNAVAILABLE",
        ),
        ({"exitCode": 0, "stdout": "not-json", "stderr": ""}, "BROWSER_DRIVER_PROTOCOL_INVALID"),
        ({"exitCode": 0, "stdout": "{}", "stderr": ""}, "BROWSER_DRIVER_UNAVAILABLE"),
        (None, "BROWSER_DRIVER_UNAVAILABLE"),
    ],
)
async def test_browser_preflight_failure_ends_the_turn_before_any_action(store, result, code):
    model = Calls([{"name": "probe", "arguments": "{}"}] * 30)
    runtime = Runtime(store, model, settings=Settings(browser={"enabled": True}))
    commands, actions = [], []

    async def runner(argv, **kwargs):
        commands.append(argv[2])
        if result is None:
            raise OSError("private-path-must-not-be-exposed")
        return result

    async def probe(args, binding):
        await runtime.browser.capabilities()
        actions.append("action-started")
        return {"ok": True}

    runtime.browser.runner = runner
    runtime.tools.directory = None
    runtime.tools.add(
        Tool("probe", "Read after browser readiness", object_schema({}), probe, main=True)
    )
    try:
        turn = await claimed_turn(runtime)
        with pytest.raises(DomainError, match=code):
            await runtime.loop.run(turn, "main")
        assert model.calls == 1 and commands == ["capabilities"] and not actions
        record = await store.call(
            lambda db: row(
                db,
                "SELECT x.state,m.content_json FROM tool_calls x JOIN messages m ON m.id=x.result_message_id WHERE x.turn_id=?",
                (turn["id"],),
            )
        )
        value = json.loads(json.loads(record["content_json"])["text"])
        assert record["state"] == "failed"
        assert (
            value["error"] == code
            and value["executionStarted"] is False
            and value["retryable"] is False
        )
        assert "private-path" not in json.dumps(value)
    finally:
        await runtime.close()


async def test_same_error_code_after_read_execution_is_not_mislabeled_as_preflight(store):
    model = Calls([{"name": "probe", "arguments": "{}"}] * 2)
    runtime, reads = Runtime(store, model), []

    async def read(args, binding):
        reads.append(True)
        raise DomainError("BROWSER_DRIVER_UNAVAILABLE")

    runtime.tools.directory = None
    runtime.tools.add(Tool("probe", "Read a resource", object_schema({}), read, main=True))
    try:
        assert await runtime.loop.run(await claimed_turn(runtime), "main") == "Done"
        assert model.calls == 3 and len(reads) == 2
        assert all("executionStarted" not in value for value in model.results)
    finally:
        await runtime.close()


@pytest.mark.parametrize("endpoint", ["", "http://127.0.0.1:53455"])
async def test_managed_discovery_is_optional_and_explicit_endpoints_are_preserved(store, endpoint):
    runtime = Runtime(
        store, Calls([]), settings=Settings(browser={"enabled": True, "endpoint": endpoint})
    )
    commands = []

    async def runner(argv, **kwargs):
        commands.append(argv)
        return {"exitCode": 0, "stdout": json.dumps(CAPS), "stderr": ""}

    runtime.browser.runner = runner
    try:
        assert await runtime.browser.capabilities() == CAPS
        assert len(commands) == 1
        assert ("--cdp" in commands[0]) == bool(endpoint)
        if endpoint:
            assert commands[0][commands[0].index("--cdp") + 1] == endpoint
    finally:
        await runtime.close()


async def test_preflight_failure_is_reported_as_a_nonretryable_dependency_failure(store):
    from test_runtime import ConversationModel, until

    call = {
        "name": "bash",
        "arguments": json.dumps(
            {
                "argv": [
                    "roami",
                    "agent",
                    "capability",
                    "call",
                    "browser_open",
                    "--input",
                    json.dumps({"url": "https://example.com"}),
                ]
            }
        ),
    }
    worker = Calls([call] * 30)
    runtime = Runtime(
        store,
        ConversationModel(),
        worker_model=worker,
        settings=Settings(browser={"enabled": True}),
    )
    commands = []

    async def offline(argv, **kwargs):
        commands.append(argv[2])
        return {"exitCode": 1, "stdout": "", "stderr": "Connection refused"}

    runtime.browser.runner = offline
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice",
            conversation["id"],
            "Read the requested page",
            key="offline-browser",
            target={"kind": "new_session", "resourceOnly": True},
            record_intent=True,
        )
        await runtime.start()
        await until(
            store,
            lambda db: row(db, "SELECT id FROM tasks WHERE id=? AND state='failed'", (task["id"],)),
        )
        result = await store.call(
            lambda db: row(
                db, "SELECT result_json FROM task_attempts WHERE task_id=?", (task["id"],)
            )
        )
        value = json.loads(result["result_json"])
        assert value["errorCode"] == "BROWSER_DRIVER_UNAVAILABLE"
        assert value["retryable"] is False and value["executionStarted"] is False
        assert value.get("outcomeKnown") is not False
        assert worker.calls == 1 and commands == ["capabilities"]
    finally:
        await runtime.close()
