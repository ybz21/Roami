"""A stopped navigation from a previous installation still requires durable proof to retry."""

import json

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import event, row, rows
from roami_agent.storage.transcript_repository import message


async def interrupted_navigation(store, mode="act"):
    runtime = Runtime(store, ConversationModel())
    conversation = await runtime.conversations.create("alice")
    task = await runtime.tasks.create(
        "alice",
        conversation["id"],
        "Check pricing",
        key="lookup",
        record_intent=True,
        target={"kind": "new_session", "resourceOnly": True},
    )
    url = "https://fixture.example/pricing"

    def history(db):
        run = row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
        branch = row(db, "SELECT * FROM branches WHERE id=?", (run["native_branch_id"],))
        child = branch["conversation_id"]
        db.execute(
            "INSERT INTO turns(id,conversation_id,branch_id,trigger_kind,state,created_ms) "
            "VALUES('old-turn',?,?,'continuation','interrupted',1)",
            (child, branch["id"]),
        )
        event(
            db, child, "task.started", {"runId": run["id"]}, turn_id="old-turn", task_id=task["id"]
        )
        call = {"id": "lookup", "function": {"name": "browser_" + mode}}
        args = (
            {"url": url}
            if mode == "open"
            else {"kind": "goto", "url": url, "observationId": "page"}
        )
        call["function"]["arguments"] = encoded(args)
        assistant = message(
            db, child, branch["id"], "assistant", {"tool_calls": [call]}, turn_id="old-turn"
        )
        db.execute(
            "INSERT INTO tool_calls(id,turn_id,assistant_message_id,tool_name,arguments_json,effect,state,idempotency_key,created_ms,updated_ms) "
            "VALUES('unknown-call','old-turn',?,?,?,'write','unknown','lookup',1,1)",
            (assistant, call["function"]["name"], encoded(args)),
        )
        db.execute(
            "INSERT INTO resources(id,node_id,kind,resource_key) VALUES('tab','local','browser','old-tab')"
        )
        for observation, verb, state in [
            ("blank", "new", "succeeded"),
            ("page", "goto", "unknown"),
        ]:
            db.execute(
                "INSERT INTO resource_observations VALUES(?, 'tab', ?, ?, 1, 1, 'snapshot', '{}', 1)",
                (observation, task["id"], run["id"]),
            )
            db.execute(
                "INSERT INTO resource_actions(id,resource_id,task_id,run_id,lease_epoch,observation_id,idempotency_key,payload_sha256,action_json,state,result_json,created_ms,updated_ms) "
                "VALUES(?,'tab',?,?,1,?,?,?,?,?,?,1,1)",
                (
                    verb,
                    task["id"],
                    run["id"],
                    observation,
                    "old-turn:lookup:" + verb,
                    "a" * 64,
                    encoded({"verb": verb, "args": [url]}),
                    state,
                    encoded({"inputStopped": True}),
                ),
            )
        db.execute("UPDATE tasks SET state='interrupted' WHERE id=?", (task["id"],))
        db.execute(
            "UPDATE task_attempts SET state='unknown',result_json=? WHERE id=?",
            (
                encoded(
                    {"summary": "TOOL_OUTCOME_UNKNOWN", "inputStopped": True, "outcomeKnown": False}
                ),
                run["id"],
            ),
        )

    await store.call(history, write=True)
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
