import pytest
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_coordination import delegated_team as delegated_team_fixture

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.swarm_member_yield import advance, current_yield_request

coordination = coordination_fixture
delegated_team = delegated_team_fixture


@pytest.fixture
async def yielding(coordination):
    runtime, _, team, _, _, actor = coordination
    await runtime.db.call(
        lambda db: (
            db.execute("UPDATE tasks SET state='running' WHERE id=?", (actor["taskId"],)),
            db.execute("UPDATE task_attempts SET state='running' WHERE id=?", (actor["runId"],)),
        ),
        write=True,
    )
    spec = {
        "commandKey": "yield-question",
        "messageKey": "needs-main",
        "kind": "question",
        "text": "Please decide between the two current candidates.",
        "yieldToMain": True,
    }
    result = await runtime.swarms.post("alice", team["id"], spec, binding=actor)
    return runtime, team, actor, spec, result


async def test_yield_request_is_atomic_idempotent_and_not_a_stop_receipt(yielding):
    runtime, team, actor, spec, result = yielding
    assert result["acceptedOnly"] is True and result["yieldState"] == "requested"
    assert await runtime.swarms.post("alice", team["id"], spec, binding=actor) == result
    task = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (actor["taskId"],))
    )
    assert task["state"] == "running"
    first = await runtime.db.call(lambda db: advance(db, result["operationId"]), write=True)
    assert first["cancellationEventId"]
    assert await runtime.db.call(lambda db: advance(db, result["operationId"]), write=True) == first
    task = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (actor["taskId"],))
    )
    assert task["state"] == "cancelling"


@pytest.mark.parametrize(
    "fault",
    ["revision", "run", "receipt", "owner", "swarm", "goal_revision", "revoked", "archived"],
)
async def test_yield_does_not_cancel_a_replaced_run_or_uncommitted_message(yielding, fault):
    runtime, _, actor, _, result = yielding

    def change(db):
        if fault == "revision":
            db.execute("UPDATE tasks SET revision=revision+1 WHERE id=?", (actor["taskId"],))
        elif fault == "run":
            db.execute(
                "UPDATE jobs SET payload_json=json_set(payload_json,'$.runId','foreign-run') WHERE id=?",
                (result["operationId"],),
            )
        elif fault in {"owner", "swarm", "goal_revision"}:
            field, value = {
                "owner": ("owner", "foreign-owner"),
                "swarm": ("swarmId", "foreign-swarm"),
                "goal_revision": ("delegationRevision", 999),
            }[fault]
            db.execute(
                "UPDATE jobs SET payload_json=json_set(payload_json,?,?) WHERE id=?",
                ("$." + field, value, result["operationId"]),
            )
        elif fault == "revoked":
            db.execute(
                "UPDATE swarm_goal_delegations SET revoked_ms=1,revoked_by_message_id=source_message_id"
            )
        elif fault == "archived":
            db.execute("UPDATE swarm_groups SET archived=1")
        else:
            db.execute("DELETE FROM swarm_commands WHERE command_key='yield-question'")

    await runtime.db.call(change, write=True)
    if fault == "receipt":
        with pytest.raises(DomainError, match="SWARM_MEMBER_YIELD_RECEIPT_UNAVAILABLE"):
            await runtime.db.call(lambda db: advance(db, result["operationId"]), write=True)
    else:
        assert (await runtime.db.call(lambda db: advance(db, result["operationId"]), write=True))[
            "skipped"
        ]
    task = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (actor["taskId"],))
    )
    assert task["state"] == "running"


async def test_later_user_stop_overrides_yield_cancellation_identity(yielding):
    runtime, _, actor, _, result = yielding
    await runtime.db.call(lambda db: advance(db, result["operationId"]), write=True)

    def proof(db):
        task = row(db, "SELECT * FROM tasks WHERE id=?", (actor["taskId"],))
        run = row(db, "SELECT * FROM task_attempts WHERE id=?", (actor["runId"],))
        return current_yield_request(db, task, run)

    assert await runtime.db.call(proof)
    await runtime.tasks.cancel("alice", actor["taskId"], expected_revision=actor["taskRevision"])
    assert await runtime.db.call(proof) is None


@pytest.mark.parametrize("known", [True, False, None])
async def test_only_real_known_stop_records_member_yield(yielding, known):
    runtime, _, actor, _, result = yielding
    await runtime.db.call(lambda db: advance(db, result["operationId"]), write=True)
    report = {"state": "cancelled", "summary": "Native input stopped"}
    if known is not None:
        report.update(inputStopped=known, outcomeKnown=known)
    await runtime.tasks.report(
        "alice", actor["taskId"], actor["runId"], actor["taskRevision"], report
    )
    task, run = await runtime.db.call(
        lambda db: (
            row(db, "SELECT * FROM tasks WHERE id=?", (actor["taskId"],)),
            row(db, "SELECT * FROM task_attempts WHERE id=?", (actor["runId"],)),
        )
    )
    await runtime.dispatch.complete(task, run, report, "cancelled")
    # Inspect the persisted completion, never the author's report.
    events = await runtime.db.call(
        lambda db: db.execute(
            "SELECT payload_json FROM events WHERE task_id=? ORDER BY id", (actor["taskId"],)
        ).fetchall()
    )
    assert any("yieldedToMain" in e[0] for e in events) is (known is True)
    if known is True:
        current = await runtime.db.call(
            lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (actor["taskId"],))
        )
        assert current["state"] == "interrupted"


def test_legacy_member_message_omits_default_flag_from_retry_identity():
    from roami_agent.server.swarm_routes import MemberPost

    original = {
        "commandKey": "old-key",
        "text": "progress",
        "taskId": "task",
        "runId": "run",
        "taskRevision": 1,
    }
    body = MemberPost(**original).model_dump(exclude_none=True)
    assert "yieldToMain" not in body
    assert (
        MemberPost(**original, yieldToMain=True).model_dump(exclude_none=True)["yieldToMain"]
        is True
    )


@pytest.mark.parametrize("bad", [1, "true", None])
def test_member_yield_flag_requires_explicit_boolean(bad):
    from pydantic import ValidationError

    from roami_agent.server.swarm_routes import MemberPost

    with pytest.raises(ValidationError):
        MemberPost(
            commandKey="key",
            text="question",
            taskId="task",
            runId="run",
            taskRevision=1,
            yieldToMain=bad,
        )


@pytest.mark.parametrize("initial_known", [False, None])
@pytest.mark.parametrize("later_control", [None, "user_stop", "goal_revoked"])
async def test_unknown_stop_keeps_directory_reserved_and_later_proof_resumes(
    yielding, initial_known, later_control
):
    import json

    from roami_agent.dispatch.workspace_queue import occupied_directories

    runtime, _, actor, _, request = yielding
    await runtime.db.call(lambda db: advance(db, request["operationId"]), write=True)
    initial = {"state": "cancelled", "summary": "Stop observation"}
    if initial_known is not None:
        initial.update(inputStopped=False, outcomeKnown=False)

    async def settle(report):
        await runtime.tasks.report(
            "alice", actor["taskId"], actor["runId"], actor["taskRevision"], report
        )
        task, run = await runtime.db.call(
            lambda db: (
                row(db, "SELECT * FROM tasks WHERE id=?", (actor["taskId"],)),
                row(db, "SELECT * FROM task_attempts WHERE id=?", (actor["runId"],)),
            )
        )
        await runtime.dispatch.complete(task, run, report, "cancelled")

    await settle(initial)
    task, run = await runtime.db.call(
        lambda db: (
            row(db, "SELECT * FROM tasks WHERE id=?", (actor["taskId"],)),
            row(db, "SELECT * FROM task_attempts WHERE id=?", (actor["runId"],)),
        )
    )
    assert task["state"] == "cancelling" and run["state"] == "unknown"
    assert json.loads(run["result_json"]) == initial
    task["native_binding_json"] = json.dumps({"directory": "/tmp/isolated-project"})
    assert ("local", "/tmp/isolated-project") in occupied_directories([task], {})[0]
    if later_control == "user_stop":
        await runtime.tasks.cancel(
            "alice", actor["taskId"], expected_revision=actor["taskRevision"]
        )
    elif later_control == "goal_revoked":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE swarm_goal_delegations SET revoked_ms=1,revoked_by_message_id=source_message_id"
            ),
            write=True,
        )
    await settle(
        {
            "state": "cancelled",
            "summary": "Verified native stop",
            "inputStopped": True,
            "outcomeKnown": True,
        }
    )
    assert (
        await runtime.db.call(
            lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (actor["taskId"],))
        )
    )["state"] == ("interrupted" if later_control is None else "cancelled")


async def test_cli_monitor_reconciles_original_pending_yield_before_waking_main(
    yielding, monkeypatch
):
    from unittest.mock import AsyncMock

    from roami_agent.executors.roami_cli import CodingExecutor
    from roami_agent.server.configuration import Settings
    from roami_agent.storage.swarm_inbox_wakeup import advance as wake_main

    runtime, team, actor, _, request = yielding
    await runtime.db.call(lambda db: advance(db, request["operationId"]), write=True)
    unknown = {
        "state": "cancelled",
        "summary": "Stop unconfirmed",
        "inputStopped": False,
        "outcomeKnown": False,
    }
    await runtime.tasks.report(
        "alice", actor["taskId"], actor["runId"], actor["taskRevision"], unknown
    )
    task, run = await runtime.db.call(
        lambda db: (
            row(db, "SELECT * FROM tasks WHERE id=?", (actor["taskId"],)),
            row(db, "SELECT * FROM task_attempts WHERE id=?", (actor["runId"],)),
        )
    )
    await runtime.dispatch.complete(task, run, unknown, "cancelled")
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE jobs SET state='done' WHERE kind='task.run' AND aggregate_id=?",
            (actor["taskId"],),
        ),
        write=True,
    )
    executor = CodingExecutor(runtime.db, Settings())
    known = {
        "state": "cancelled",
        "result": {
            "state": "cancelled",
            "summary": "Fixture Go stop proof",
            "inputStopped": True,
            "outcomeKnown": True,
        },
    }
    command = AsyncMock(return_value=known)
    monkeypatch.setattr(executor, "command", command)
    monkeypatch.setattr(executor, "cancel", AsyncMock())
    monkeypatch.setattr(executor, "record", AsyncMock())
    monkeypatch.setattr(executor, "reconcile_observation", AsyncMock(return_value=known))
    await executor.poll(runtime.tasks)
    command.assert_awaited_once_with("status", "--key", run["launch_id"])
    current = await runtime.db.call(
        lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (actor["taskId"],))
    )
    assert current["state"] == "cancelling"
    verify = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT * FROM jobs WHERE kind='task.verify' AND aggregate_id=? ORDER BY rowid DESC LIMIT 1",
            (actor["taskId"],),
        )
    )
    await runtime.dispatch.verify(verify)
    current = await runtime.db.call(
        lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (actor["taskId"],))
    )
    assert current["state"] == "interrupted"
    wake = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT id FROM jobs WHERE kind='swarm.inbox.wakeup' AND json_extract(payload_json,'$.inboxId')=(SELECT id FROM swarm_inbox WHERE post_id=?)",
            (request["id"],),
        )
    )
    batch = await runtime.db.call(lambda db: wake_main(db, wake["id"]), write=True)
    turn = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM turns WHERE id=?", (batch["turnId"],))
    )
    assert turn["conversation_id"] == team["mainConversationId"] and turn["state"] == "queued"


async def test_scheduler_keeps_original_main_behind_member_until_known_yield(
    yielding, monkeypatch, tmp_path
):
    import asyncio
    import json
    from types import SimpleNamespace

    from test_swarm_delegations import finish

    import roami_agent.dispatch.scheduler as scheduling
    from roami_agent.storage.swarm_inbox_wakeup import advance as wake_main

    runtime, team, actor, _, request = yielding
    wake = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT id FROM jobs WHERE kind='swarm.inbox.wakeup' AND json_extract(payload_json,'$.inboxId')=(SELECT id FROM swarm_inbox WHERE post_id=?)",
            (request["id"],),
        )
    )
    batch = await runtime.db.call(lambda db: wake_main(db, wake["id"]), write=True)
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE jobs SET state='done' WHERE id!=? AND kind!='task.yield'",
            (
                row(
                    db,
                    "SELECT id FROM jobs WHERE kind='turn.run' AND aggregate_id=?",
                    (batch["turnId"],),
                )["id"],
            ),
        ),
        write=True,
    )
    directory = json.dumps(
        {"directory": str(tmp_path), "providerConversationId": "original-provider-fixture"}
    )
    monkeypatch.setattr(scheduling, "native_member_binding", lambda db, task_id: directory)
    started = []

    async def run_main(turn, *args, **kwargs):
        started.append(turn["conversation_id"])
        await finish(runtime, turn)

    scheduler = scheduling.Scheduler(
        runtime.db,
        SimpleNamespace(workers=8, main_concurrency=1),
        None,
        runtime.dispatch,
        runtime.mailbox,
        run_main,
        asyncio.Event(),
        {},
        None,
        native_turn_binding=lambda db, turn_id: directory,
    )

    async def scan():
        await scheduler._scan()
        await asyncio.gather(*(v["handle"] for v in list(scheduler.active.values())))
        await asyncio.sleep(0)

    await scan()
    assert started == []

    async def settle(known):
        report = {
            "state": "cancelled",
            "summary": "Fixture native stop",
            "inputStopped": known,
            "outcomeKnown": known,
        }
        await runtime.tasks.report(
            "alice", actor["taskId"], actor["runId"], actor["taskRevision"], report
        )
        task, run = await runtime.db.call(
            lambda db: (
                row(db, "SELECT * FROM tasks WHERE id=?", (actor["taskId"],)),
                row(db, "SELECT * FROM task_attempts WHERE id=?", (actor["runId"],)),
            )
        )
        await runtime.dispatch.complete(task, run, report, "cancelled")

    await settle(False)
    await scan()
    assert started == []
    await settle(True)
    await scan()
    assert started == [team["mainConversationId"]]


async def test_normal_progress_does_not_request_stop(yielding):
    runtime, team, actor, _, _ = yielding
    before = await runtime.db.call(
        lambda db: db.execute("SELECT COUNT(*) FROM jobs WHERE kind='task.yield'").fetchone()[0]
    )
    await runtime.swarms.post(
        "alice",
        team["id"],
        {
            "commandKey": "normal-progress",
            "text": "Still executing a healthy long step.",
            "kind": "progress",
        },
        binding=actor,
    )
    assert (
        await runtime.db.call(
            lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (actor["taskId"],))
        )
    )["state"] == "running"
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT COUNT(*) FROM jobs WHERE kind='task.yield'").fetchone()[0]
        )
        == before
    )


async def test_main_answer_continues_original_task_session_and_provider(yielding, tmp_path):
    import json

    from test_swarm_coordination import claim
    from test_swarm_delegations import finish

    from roami_agent.storage.swarm_inbox_wakeup import advance as wake_main

    runtime, team, actor, _, request = yielding

    async def workspace(project):
        assert project == "project-a"
        return {"projectId": project, "directory": str(tmp_path)}

    runtime.tasks.revisions.project_workspace = workspace
    await runtime.db.call(
        lambda db: (
            db.execute(
                "UPDATE task_attempts SET session_id='original-session',agent_conversation_id='original-provider' WHERE id=?",
                (actor["runId"],),
            ),
            db.execute(
                "UPDATE tasks SET target_json=? WHERE id=?",
                (
                    json.dumps(
                        {
                            "sessionId": "original-session",
                            "workdir": str(tmp_path),
                            "workspace": {"directory": str(tmp_path)},
                        }
                    ),
                    actor["taskId"],
                ),
            ),
        ),
        write=True,
    )
    await runtime.db.call(lambda db: advance(db, request["operationId"]), write=True)
    report = {
        "state": "cancelled",
        "summary": "Fixture Go stop proof",
        "inputStopped": True,
        "outcomeKnown": True,
    }
    await runtime.tasks.report(
        "alice", actor["taskId"], actor["runId"], actor["taskRevision"], report
    )
    verify = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT * FROM jobs WHERE kind='task.verify' AND aggregate_id=? ORDER BY rowid DESC LIMIT 1",
            (actor["taskId"],),
        )
    )
    await runtime.dispatch.verify(verify)
    wake = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT id FROM jobs WHERE kind='swarm.inbox.wakeup' AND json_extract(payload_json,'$.inboxId')=(SELECT id FROM swarm_inbox WHERE post_id=?)",
            (request["id"],),
        )
    )
    batch = await runtime.db.call(lambda db: wake_main(db, wake["id"]), write=True)
    turn = await claim(runtime, batch)
    assert turn["conversation_id"] == team["mainConversationId"]
    binding = {
        "conversation": team["mainConversationId"],
        "turnId": turn["id"],
        "leaseEpoch": turn["lease_epoch"],
    }
    reply = await runtime.swarms.post(
        "alice",
        team["id"],
        {
            "commandKey": "main-answer",
            "messageKey": "answer-original-question",
            "kind": "reply",
            "replyTo": request["id"],
            "text": "Continue the current candidate; do not publish.",
        },
        binding=binding,
    )
    assert reply["id"] != request["id"]
    continued = await runtime.tasks.revisions.request(
        "alice",
        actor["taskId"],
        "Continue the current candidate; do not publish.",
        actor["taskRevision"],
        "resume-yielded-original",
        source_turn_id=turn["id"],
        source_conversation_id=team["mainConversationId"],
        source_lease_epoch=turn["lease_epoch"],
    )
    await finish(runtime, turn)
    await runtime.tasks.revisions.advance()
    receipt = await runtime.tasks.revisions.get("alice", actor["taskId"], continued["operationId"])
    assert receipt["state"] == "applied" and receipt["revision"] == 2
    current = await runtime.db.call(
        lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (actor["taskId"],))
    )
    intent = json.loads(current["intent_json"])
    assert intent["target"]["sessionId"] == "original-session"
    assert intent["continuation"]["providerRunId"] == actor["runId"]
    assert (
        await runtime.db.call(
            lambda db: row(
                db, "SELECT agent_conversation_id FROM task_attempts WHERE id=?", (actor["runId"],)
            )
        )
    )["agent_conversation_id"] == "original-provider"


@pytest.mark.parametrize("user_stop", [False, True])
async def test_monitor_survives_restart_after_yield_before_run_job_cleanup(
    yielding, monkeypatch, user_stop
):
    from unittest.mock import AsyncMock

    from roami_agent.executors.roami_cli import CodingExecutor
    from roami_agent.server.configuration import Settings

    runtime, _, actor, _, request = yielding
    await runtime.db.call(lambda db: advance(db, request["operationId"]), write=True)
    await runtime.db.call(
        lambda db: db.execute(
            "UPDATE jobs SET state='running' WHERE kind='task.run' AND aggregate_id=?",
            (actor["taskId"],),
        ),
        write=True,
    )
    if user_stop:
        await runtime.tasks.cancel(
            "alice", actor["taskId"], expected_revision=actor["taskRevision"]
        )
    executor = CodingExecutor(runtime.db, Settings())
    runtime.executor = runtime.dispatch.executor = executor
    command = AsyncMock(return_value={"state": "running"})
    monkeypatch.setattr(executor, "command", command)
    monkeypatch.setattr(executor, "cancel", AsyncMock())
    monkeypatch.setattr(executor, "record", AsyncMock())
    monkeypatch.setattr(
        executor, "reconcile_observation", AsyncMock(return_value={"state": "running"})
    )
    await runtime.dispatch.recover()
    await executor.poll(runtime.tasks)
    assert command.await_count == 1, (
        "Original native execution must remain observable after restart"
    )
