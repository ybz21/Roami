"""A user can continue stopped navigation; unknown writes and missing proof stay blocked."""

import json

import pytest
from test_browser_driver import BrowserFixture
from test_runtime import ConversationModel, until

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.protocol.serialization import encoded
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row, rows


class NavigationModel:
    model = "unknown-navigation"

    def __init__(self, mode):
        self.mode, self.calls = mode, 0

    async def stream(self, messages, tools):
        self.calls += 1
        if self.mode == "act" and self.calls > 1:
            name, arguments = (
                "browser_act",
                {
                    "observationId": json.loads(messages[-1]["content"])["observation"]["id"],
                    "kind": "goto",
                    "url": "https://fixture.example/pricing",
                },
            )
        else:
            name, arguments = (
                "browser_open",
                ({"url": "https://fixture.example/pricing"} if self.mode == "open" else {}),
            )
        yield ModelEvent(
            "tool",
            {
                "id": "lookup-" + str(self.calls),
                "function": {
                    "name": name,
                    "arguments": encoded(arguments),
                },
            },
        )


async def interrupted_navigation(store, mode="act"):
    fixture = BrowserFixture()

    async def runner(argv, **options):
        result = await fixture(argv, **options)
        verb, flags, _ = fixture.arguments(argv)
        if verb == "goto":
            receipt = fixture.receipts[flags["--operation-id"]]
            receipt.update(state="unknown", inputStopped=True, outcomeKnown=False)
            result["stdout"] = encoded(receipt)
        return result

    runtime = Runtime(
        store,
        ConversationModel(),
        worker_model=NavigationModel(mode),
        settings=Settings(browser={"enabled": True}),
    )
    runtime.browser.runner = runner
    # Preserve the legacy gateway's failure after a stopped unknown navigation receipt.
    for name in ("browser_open", "browser_act"):
        tool = runtime.tools.registry[name]

        async def legacy_handler(args, binding, handler=tool.handler):
            value = await handler(args, binding)
            if value.get("action", {}).get("state") == "unknown":
                raise DomainError("TOOL_OUTCOME_UNKNOWN")
            return value

        tool.handler = legacy_handler
    await runtime.start()
    conversation = await runtime.conversations.create("alice")
    task = await runtime.tasks.create(
        "alice",
        conversation["id"],
        "Check pricing",
        target={"kind": "new_session", "resourceOnly": True},
        key="lookup",
        record_intent=True,
    )
    runtime.wakeup.set()
    await until(
        store,
        lambda db: row(
            db, "SELECT id FROM tasks WHERE id=? AND state='interrupted'", (task["id"],)
        ),
    )
    # Keep the fixture's next revision queued while checking durable admission.
    runtime.scheduler.stopping = True
    await runtime.supervisor
    return runtime, task


@pytest.mark.parametrize("mode", ["open", "act"])
@pytest.mark.parametrize("summary", ["TOOL_OUTCOME_UNKNOWN", "TOOL_STOP_UNCONFIRMED"])
async def test_stopped_navigation_continues_original_task_and_keeps_unknown_history(
    store, mode, summary
):
    runtime, task = await interrupted_navigation(store, mode)
    try:
        await store.call(
            lambda db: db.execute(
                "UPDATE task_attempts SET result_json=json_set(result_json,'$.summary',?) WHERE task_id=?",
                (summary, task["id"]),
            ),
            write=True,
        )
        old = (await runtime.tasks.get("alice", task["id"]))["attempts"][0]
        operation = await runtime.tasks.revisions.request(
            "alice", task["id"], "Try again", 1, "retry"
        )
        assert (
            await runtime.tasks.revisions.request("alice", task["id"], "Try again", 1, "retry")
            == operation
        )
        await runtime.tasks.revisions.advance()
        assert (await runtime.tasks.revisions.get("alice", task["id"], operation["operationId"]))[
            "state"
        ] == "applied"
        attempts = await store.call(
            lambda db: rows(
                db, "SELECT * FROM task_attempts WHERE task_id=? ORDER BY attempt_no", (task["id"],)
            )
        )
        assert len(attempts) == 2 and attempts[1]["task_revision"] == 2
        assert attempts[0]["state"] == "unknown"
        assert json.loads(attempts[0]["result_json"]) == old["result"]
        assert await store.call(
            lambda db: row(db, "SELECT id FROM tool_calls WHERE state='unknown'")
        )
        events = await store.call(
            lambda db: rows(
                db, "SELECT payload_json FROM events WHERE kind='task.navigation_recovery'"
            )
        )
        assert len(events) == 1
        proof = json.loads(events[0]["payload_json"])
        assert proof["inputStopped"] is True and proof["outcomeKnown"] is False
        assert len(proof["actionIds"]) == 2 and len(proof["toolCallIds"]) == 1
        with pytest.raises(DomainError, match="TASK_REVISION_CHANGED"):
            await runtime.tasks.revisions.request("alice", task["id"], "Stale", 1, "stale")
        with pytest.raises(DomainError, match="TASK_NOT_FOUND"):
            await runtime.tasks.revisions.request("bob", task["id"], "Other owner", 2, "other")
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE resource_actions SET result_json=json_set(result_json,'$.inputStopped',json('false')) WHERE state='unknown'",
        "UPDATE resource_actions SET action_json=json_set(action_json,'$.verb','click') WHERE state='unknown'",
        "UPDATE resource_actions SET state='running' WHERE state='unknown'",
        "UPDATE resource_actions SET idempotency_key='other-turn:lookup:act' WHERE state='unknown'",
        "DELETE FROM resource_actions WHERE state='unknown'",
        "DELETE FROM events WHERE kind='task.started'",
        "UPDATE turns SET state='running' WHERE id IN (SELECT turn_id FROM tool_calls WHERE state='unknown')",
        "UPDATE tool_calls SET tool_name='file_write' WHERE state='unknown'",
        "UPDATE tool_calls SET state='planned' WHERE state='unknown'",
        "UPDATE tasks SET intent_json=json_set(intent_json,'$.target.resourceOnly',json('false'))",
        "UPDATE task_attempts SET executor_kind='cli'",
        "UPDATE tool_calls SET arguments_json=json_set(arguments_json,'$.url','https://other.example') WHERE state='unknown'",
        "UPDATE tool_calls SET arguments_json=json_set(arguments_json,'$.kind','fill') WHERE state='unknown'",
        "UPDATE resource_actions SET observation_id=(SELECT observation_id FROM resource_actions WHERE state='succeeded') WHERE state='unknown'",
    ],
)
async def test_missing_stop_or_non_navigation_effects_do_not_admit_a_retry(store, change):
    runtime, task = await interrupted_navigation(store)
    try:
        await store.call(lambda db: db.execute(change), write=True)
        with pytest.raises(DomainError, match="TASK_OUTCOME_UNRESOLVED"):
            await runtime.tasks.revisions.request("alice", task["id"], "Try again", 1, "retry")
        assert not await store.call(
            lambda db: row(db, "SELECT id FROM events WHERE kind='task.navigation_recovery'")
        )
        assert (await runtime.tasks.get("alice", task["id"]))["task"]["revision"] == 1
    finally:
        await runtime.close()


async def test_stop_evidence_is_rechecked_before_a_queued_continuation_is_applied(store):
    runtime, task = await interrupted_navigation(store)
    try:
        operation = await runtime.tasks.revisions.request(
            "alice", task["id"], "Try again", 1, "retry"
        )
        await store.call(
            lambda db: db.execute(
                "UPDATE resource_actions SET result_json=json_set(result_json,'$.inputStopped',json('false')) WHERE state='unknown'"
            ),
            write=True,
        )
        await runtime.tasks.revisions.advance()
        receipt = await runtime.tasks.revisions.get("alice", task["id"], operation["operationId"])
        assert receipt["state"] == "blocked" and receipt["errorCode"] == "TASK_OUTCOME_UNRESOLVED"
        assert (await runtime.tasks.get("alice", task["id"]))["task"]["revision"] == 1
    finally:
        await runtime.close()
