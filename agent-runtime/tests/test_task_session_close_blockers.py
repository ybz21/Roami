"""Native archival preserves unknown outcomes while live execution still blocks closing."""

import json

import pytest
from test_native_session_storage import native
from test_task_session_closure import close_job

from roami_agent.dispatch.task_sessions import TaskSessions
from roami_agent.protocol.identity import identity
from roami_agent.storage.database import row
from roami_agent.storage.transcript_repository import message


async def test_unfinished_unknown_native_attempt_archives_without_changing_evidence(store):
    sessions, session, _, task = await native(store)

    def interrupt(db):
        db.execute("UPDATE tasks SET state='interrupted' WHERE id=?", (task["id"],))
        db.execute(
            "UPDATE task_attempts SET state='unknown',finished_ms=NULL,"
            "result_json=? WHERE task_id=?",
            (
                json.dumps({"outcomeKnown": False, "summary": "Original outcome unknown"}),
                task["id"],
            ),
        )
        return row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))

    attempt = await store.call(interrupt, write=True)
    service = TaskSessions(store, None)
    await service.request("alice", task["id"], 1, attempt["id"])
    await service.advance(await close_job(store, task["id"]))

    view = await sessions.get("alice", session["id"])
    assert view["lifecycle"] == "closed"
    assert view["closureError"] is None
    assert await sessions.list("alice") == []
    assert await store.call(
        lambda db: row(db, "SELECT state FROM task_session_closures WHERE task_id=?", (task["id"],))
    ) == {"state": "closed"}
    assert (await close_job(store, task["id"]))["state"] == "done"
    assert (
        await store.call(
            lambda db, attempt=attempt: row(
                db, "SELECT * FROM task_attempts WHERE id=?", (attempt["id"],)
            )
        )
        == attempt
    )
    assert await store.call(
        lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],))
    ) == {"state": "interrupted"}


@pytest.mark.parametrize("tool_state", ["unknown", "planned", "running"])
async def test_historical_native_unknown_tool_is_retained_but_active_tools_still_wait(
    store, tool_state
):
    sessions, session, _, task = await native(store)
    turn_id, call_id, new_run = identity(), identity(), identity()

    def prepare(db):
        original = row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
        db.execute(
            "UPDATE task_attempts SET state='unknown',finished_ms=NULL,"
            "result_json='{\"outcomeKnown\":false}' WHERE id=?",
            (original["id"],),
        )
        db.execute("UPDATE tasks SET revision=2,state='waiting_user' WHERE id=?", (task["id"],))
        db.execute(
            "INSERT INTO task_attempts(id,task_id,task_revision,attempt_no,executor_kind,"
            "launch_id,state,native_branch_id,result_json,lease_epoch,started_ms,finished_ms)"
            " VALUES(?,?,2,2,'native',?,'succeeded',?,'{}',1,2,3)",
            (new_run, task["id"], "close-test:" + new_run, session["branch_id"]),
        )
        active = tool_state != "unknown"
        db.execute(
            "INSERT INTO turns(id,conversation_id,branch_id,trigger_kind,state,created_ms,"
            "finished_ms,lease_owner,lease_until_ms) VALUES(?,?,?,'user',?,1,?,?,?)",
            (
                turn_id,
                session["conversation_id"],
                session["branch_id"],
                "running" if active else "failed",
                None if active else 2,
                "current-worker" if active else None,
                9999999999999 if active else None,
            ),
        )
        assistant = message(
            db,
            session["conversation_id"],
            session["branch_id"],
            "assistant",
            {"text": "Historical browser operation"},
            turn_id=turn_id,
        )
        db.execute(
            "INSERT INTO tool_calls(id,turn_id,assistant_message_id,tool_name,arguments_json,"
            "effect,state,idempotency_key,created_ms,updated_ms)"
            " VALUES(?,?,?,'browser_act','{}','write',?,?,1,2)",
            (call_id, turn_id, assistant, tool_state, call_id),
        )
        return (
            row(db, "SELECT * FROM task_attempts WHERE id=?", (original["id"],)),
            row(db, "SELECT * FROM tool_calls WHERE id=?", (call_id,)),
        )

    old_attempt, original_call = await store.call(prepare, write=True)
    service = TaskSessions(store, None)
    await service.request("alice", task["id"], 2, new_run)
    await service.advance(await close_job(store, task["id"]))

    view = await sessions.get("alice", session["id"])
    job = await close_job(store, task["id"])
    if tool_state == "unknown":
        assert view["lifecycle"] == "closed"
        assert job["state"] == "done"
        assert view["closureError"] is None
        assert await sessions.list("alice") == []
    else:
        assert view["lifecycle"] == "closing"
        assert view["closureError"] is None
        assert job["state"] == "queued"
    assert (
        await store.call(lambda db: row(db, "SELECT * FROM tool_calls WHERE id=?", (call_id,)))
        == original_call
    )
    assert (
        await store.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE id=?", (old_attempt["id"],))
        )
        == old_attempt
    )
    assert await store.call(
        lambda db: row(db, "SELECT state,revision FROM tasks WHERE id=?", (task["id"],))
    ) == {"state": "waiting_user", "revision": 2}


async def test_live_unconfirmed_execution_waits_for_stop_then_closes(store):
    from test_task_session_closure import prepare

    runtime, task, run, calls, service = await prepare(store)
    try:

        def still_running(db):
            db.execute("UPDATE tasks SET state='running' WHERE id=?", (task["id"],))
            db.execute(
                "UPDATE task_attempts SET state='running',finished_ms=NULL,result_json=? WHERE id=?",
                (json.dumps({"inputStopped": False, "outcomeKnown": False}), run["id"]),
            )

        await store.call(still_running, write=True)
        await service.request("alice", task["id"], 1, run["id"])
        await service.advance(await close_job(store, task["id"]))
        assert (await close_job(store, task["id"]))["state"] == "queued"
        assert not calls

        def stopped(db):
            db.execute("UPDATE tasks SET state='cancelled' WHERE id=?", (task["id"],))
            db.execute(
                "UPDATE task_attempts SET state='cancelled',finished_ms=1,result_json=? WHERE id=?",
                (json.dumps({"inputStopped": True, "outcomeKnown": True}), run["id"]),
            )

        await store.call(stopped, write=True)
        await service.advance(await close_job(store, task["id"]))
        assert (await close_job(store, task["id"]))["state"] == "done"
        assert len(calls) == 1
    finally:
        await runtime.close()


async def test_native_unconfirmed_input_remains_unresolved(store):
    sessions, session, _, task = await native(store)

    def prepare(db):
        db.execute("UPDATE tasks SET state='interrupted' WHERE id=?", (task["id"],))
        db.execute(
            "UPDATE task_attempts SET state='unknown',finished_ms=NULL,result_json=? WHERE task_id=?",
            (json.dumps({"inputStopped": False, "outcomeKnown": False}), task["id"]),
        )
        return row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))

    run = await store.call(prepare, write=True)
    service = TaskSessions(store, None)
    await service.request("alice", task["id"], 1, run["id"])
    await service.advance(await close_job(store, task["id"]))
    assert (await sessions.get("alice", session["id"]))["lifecycle"] == "open"
    assert (await close_job(store, task["id"]))["state"] == "failed"
    assert (await sessions.get("alice", session["id"]))["closureError"] == "TASK_OUTCOME_UNRESOLVED"


async def test_unknown_cli_attempt_still_requires_reconciliation(store):
    from test_task_session_closure import prepare

    runtime, task, run, calls, service = await prepare(store)
    try:

        def interrupt(db):
            db.execute("UPDATE tasks SET state='interrupted' WHERE id=?", (task["id"],))
            db.execute(
                "UPDATE task_attempts SET state='unknown',finished_ms=NULL,result_json=? WHERE id=?",
                (json.dumps({"outcomeKnown": False}), run["id"]),
            )

        await store.call(interrupt, write=True)
        await service.request("alice", task["id"], 1, run["id"])
        await service.advance(await close_job(store, task["id"]))
        assert (await close_job(store, task["id"]))["state"] == "failed"
        assert not calls
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "state,lease", [("held", 9999999999999), ("idle", 9999999999999), ("quarantined", None)]
)
async def test_native_archive_retains_active_or_quarantined_resource_fence(store, state, lease):
    sessions, session, _, task = await native(store)

    def prepare(db):
        db.execute("UPDATE tasks SET state='interrupted' WHERE id=?", (task["id"],))
        db.execute(
            "UPDATE task_attempts SET state='unknown',finished_ms=NULL WHERE task_id=?",
            (task["id"],),
        )
        db.execute(
            "INSERT INTO resources(id,node_id,kind,resource_key,owner_task_id,state,lease_until_ms) VALUES('original-browser','local','browser','original-browser',?,?,?)",
            (task["id"], state, lease),
        )
        return (
            row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],)),
            row(db, "SELECT * FROM resources WHERE id='original-browser'"),
        )

    run, resource = await store.call(prepare, write=True)
    service = TaskSessions(store, None)
    await service.request("alice", task["id"], 1, run["id"])
    await service.advance(await close_job(store, task["id"]))
    assert (await sessions.get("alice", session["id"]))["lifecycle"] == "closing"
    assert (await close_job(store, task["id"]))["state"] == "queued"
    assert (
        await store.call(lambda db: row(db, "SELECT * FROM resources WHERE id='original-browser'"))
        == resource
    )


async def test_native_tree_archives_children_first_and_preserves_unknown_attempts(store):
    from roami_agent.conversation.transcript import Conversations
    from roami_agent.dispatch.tasks import Tasks

    sessions, session, _, task = await native(store)
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='running' WHERE id=?", (task["id"],)),
        write=True,
    )
    child = await Tasks(store, Conversations(store)).create(
        "alice",
        session["conversation_id"],
        "Child work",
        key="archive-child",
        parent_task_id=task["id"],
    )

    def interrupt(db):
        for ident in (task["id"], child["id"]):
            db.execute("UPDATE tasks SET state='interrupted' WHERE id=?", (ident,))
            db.execute(
                "UPDATE task_attempts SET state='unknown',finished_ms=NULL,result_json='{\"outcomeKnown\":false}' WHERE task_id=?",
                (ident,),
            )
        return [
            row(db, "SELECT * FROM task_attempts WHERE task_id=?", (ident,))
            for ident in (task["id"], child["id"])
        ]

    attempts = await store.call(interrupt, write=True)
    service = TaskSessions(store, None)
    await service.request("alice", task["id"], 1, attempts[0]["id"])
    await service.advance(await close_job(store, task["id"]))
    assert (await close_job(store, task["id"]))["state"] == "done"
    assert await sessions.list("alice") == []
    for attempt in attempts:
        assert (
            await store.call(
                lambda db, attempt=attempt: row(
                    db, "SELECT * FROM task_attempts WHERE id=?", (attempt["id"],)
                )
            )
            == attempt
        )
        assert await store.call(
            lambda db, attempt=attempt: row(
                db, "SELECT state FROM tasks WHERE id=?", (attempt["task_id"],)
            )
        ) == {"state": "interrupted"}
