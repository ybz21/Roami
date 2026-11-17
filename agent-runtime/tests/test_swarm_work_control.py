import json
from unittest.mock import AsyncMock

import pytest
from test_swarm_collaboration import advance, item, plan
from test_swarm_collaboration import collaboration as collaboration_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row, rows
from roami_agent.storage.swarm_work_pause import active_pause, conversation_paused, task_paused

collaboration = collaboration_fixture
delegated_team = delegated_team_fixture


async def command(swarms, team, action, key=None):
    current = await swarms.snapshot("alice", team["id"])
    return await swarms.control(
        "alice",
        team["id"],
        {
            "action": action,
            "expectedRevision": current["revision"],
            "commandKey": key or action,
        },
    )


async def test_pause_fences_queued_work_and_resume_keeps_identity(collaboration, store):
    swarms, team = collaboration
    await plan(swarms, team, [item("a"), item("b")])
    await advance(swarms, team)
    before = (await swarms.snapshot("alice", team["id"]))["work"]
    paused = await command(swarms, team, "pause_work")
    view = await swarms.snapshot("alice", team["id"])
    assert view["workPause"] == {"state": "paused"}
    assert view["paused"]
    task = await store.call(
        lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (before[0]["task_id"],))
    )
    assert await store.call(lambda db: task_paused(db, task))
    assert await store.call(lambda db: conversation_paused(db, team["mainConversationId"]))
    for action in ["resume", "stop", "archive"]:
        with pytest.raises(DomainError, match="SWARM_WORK_ALREADY_PAUSED"):
            await command(swarms, team, action)
    resumed = await command(swarms, team, "resume_work")
    view = await swarms.snapshot("alice", team["id"])
    assert not view["paused"] and view["workPause"] is None
    assert view["revision"] == resumed["revision"] == paused["revision"] + 1
    assert [w["task_id"] for w in view["work"]] == [w["task_id"] for w in before]


async def test_pause_cancels_running_roots_and_waits_for_stop(collaboration, store):
    swarms, team = collaboration
    await plan(swarms, team, [item("a"), item("b")])
    await advance(swarms, team)
    work = (await swarms.snapshot("alice", team["id"]))["work"]
    tid = work[0]["task_id"]
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='running' WHERE id=?", (tid,)), write=True
    )
    paused = await command(swarms, team, "pause_work")
    assert (await swarms.snapshot("alice", team["id"]))["workPause"]["state"] == "stopping"
    with pytest.raises(DomainError, match="SWARM_WORK_STOPPING"):
        await command(swarms, team, "resume_work", "early-resume")
    task = await store.call(lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (tid,)))
    assert task["state"] == "cancelling"
    assert (
        await swarms.control(
            "alice",
            team["id"],
            {
                "action": "pause_work",
                "expectedRevision": paused["revision"] - 1,
                "commandKey": "pause_work",
            },
        )
        == paused
    )
    swarms.tasks.revisions.request = AsyncMock(return_value={})
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='cancelled' WHERE id=?", (tid,)), write=True
    )
    await command(swarms, team, "resume_work")
    swarms.tasks.revisions.request.assert_awaited_once()
    assert swarms.tasks.revisions.request.call_args.args[1] == tid
    # A replay after resume cannot cancel a newer run.
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='running',revision=2 WHERE id=?", (tid,)),
        write=True,
    )
    await swarms.control(
        "alice",
        team["id"],
        {
            "action": "pause_work",
            "expectedRevision": paused["revision"] - 1,
            "commandKey": "pause_work",
        },
    )
    assert (await store.call(lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (tid,))))[
        "state"
    ] == "running"


async def test_unrelated_team_and_unknown_outcome_are_preserved(collaboration, store):
    swarms, team = collaboration
    await plan(swarms, team, [item("a")])
    await advance(swarms, team)
    tid = (await swarms.snapshot("alice", team["id"]))["work"][0]["task_id"]
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='running' WHERE id=?", (tid,)), write=True
    )
    await command(swarms, team, "pause_work")
    await store.call(
        lambda db: (
            db.execute("UPDATE tasks SET state='cancelled' WHERE id=?", (tid,)),
            db.execute(
                "UPDATE task_attempts SET state='unknown',result_json=? WHERE task_id=?",
                (json.dumps({"inputStopped": False, "outcomeKnown": False}), tid),
            ),
        ),
        write=True,
    )
    with pytest.raises(DomainError, match="TASK_OUTCOME_UNRESOLVED"):
        await command(swarms, team, "resume_work")
    assert (await swarms.snapshot("alice", team["id"]))["workPause"]["state"] == "blocked"
    assert await store.call(lambda db: active_pause(db, team["id"]))
    assert not await store.call(lambda db: conversation_paused(db, "unrelated"))


async def test_pause_interrupts_only_recorded_main_turn_and_resumes_once(collaboration, store):
    swarms, team = collaboration
    main = await store.call(
        lambda db: row(
            db,
            "SELECT id FROM turns WHERE conversation_id=? AND state='queued'",
            (team["mainConversationId"],),
        )
    )
    await store.call(
        lambda db: db.execute("UPDATE turns SET state='running' WHERE id=?", (main["id"],)),
        write=True,
    )
    swarms.chat.interrupt = AsyncMock()
    await command(swarms, team, "pause_work")
    assert swarms.chat.interrupt.call_args.kwargs["expected_turn_id"] == main["id"]
    assert swarms.chat.interrupt.call_args.kwargs["pause_id"]
    await store.call(
        lambda db: db.execute("UPDATE turns SET state='interrupted' WHERE id=?", (main["id"],)),
        write=True,
    )
    swarms.chat.submit = AsyncMock()
    current = await swarms.snapshot("alice", team["id"])
    spec = {
        "action": "resume_work",
        "expectedRevision": current["revision"],
        "commandKey": "resume",
    }
    result = await swarms.control("alice", team["id"], spec)
    assert await swarms.control("alice", team["id"], spec) == result
    swarms.chat.submit.assert_awaited_once()
    assert (
        len(
            await store.call(
                lambda db: rows(db, "SELECT id FROM jobs WHERE kind='swarm.work.pause'")
            )
        )
        == 1
    )


async def test_real_runtime_stops_native_work_and_resumes_original_task(store):
    import asyncio

    from test_runtime import until

    from roami_agent.app import Runtime
    from roami_agent.protocol.models import ModelEvent

    class Model:
        model = "controlled-pause-test"
        resumed = False

        async def stream(self, messages, tools):
            if not self.resumed:
                await asyncio.Event().wait()
            yield ModelEvent("text", "Existing work preserved.")

    model = Model()
    runtime = Runtime(store, model)
    team = await runtime.swarms.create(
        "alice", {"name": "Team", "goal": "Build outputs", "commandKey": "create"}
    )
    await plan(runtime.swarms, team, [item("a", executor="native")])
    await runtime.start()
    try:
        await until(store, lambda db: row(db, "SELECT id FROM tasks WHERE state='running'"))
        before = (await runtime.swarms.snapshot("alice", team["id"]))["work"][0]
        await command(runtime.swarms, team, "pause_work")
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM tasks WHERE id=? AND state='cancelled'", (before["task_id"],)
            ),
        )
        await until(
            store,
            lambda db: (
                not row(
                    db,
                    "SELECT id FROM turns WHERE conversation_id=? AND state='running'",
                    (team["mainConversationId"],),
                )
            ),
        )
        view = await runtime.swarms.snapshot("alice", team["id"])
        assert view["workPause"] == {"state": "paused"}
        model.resumed = True
        await command(runtime.swarms, team, "resume_work")
        await until(
            store,
            lambda db: row(
                db,
                "SELECT id FROM tasks WHERE id=? AND revision=2 AND state IN ('succeeded','waiting_user')",
                (before["task_id"],),
            ),
        )
        after = (await runtime.swarms.snapshot("alice", team["id"]))["work"][0]
        assert after["task_id"] == before["task_id"]
        assert after["revision"] == 2
        assert not await store.call(lambda db: active_pause(db, team["id"]))
    finally:
        await runtime.close()


async def test_pause_stops_children_and_preserves_other_team_and_pending_input(
    collaboration, store
):
    swarms, team = collaboration
    await plan(swarms, team, [item("a", executor="native")])
    await advance(swarms, team)
    tid = (await swarms.snapshot("alice", team["id"]))["work"][0]["task_id"]
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='running' WHERE id=?", (tid,)), write=True
    )
    child = await swarms.tasks.create(
        "alice",
        team["mainConversationId"],
        "Implement child output",
        key="child",
        parent_task_id=tid,
    )
    other_main = await swarms.conversations.create("alice")
    other = await swarms.create(
        "alice",
        {
            "name": "Other team",
            "goal": "Keep working",
            "mainConversationId": other_main["id"],
            "commandKey": "other-team",
        },
    )
    await plan(swarms, other, [item("other", executor="native")], key="other-plan")
    await advance(swarms, other)
    other_tid = (await swarms.snapshot("alice", other["id"]))["work"][0]["task_id"]
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='running' WHERE id=?", (other_tid,)),
        write=True,
    )
    await command(swarms, team, "pause_work")
    tasks = await store.call(lambda db: rows(db, "SELECT id,state FROM tasks"))
    assert {t["id"]: t["state"] for t in tasks} == {
        tid: "cancelling",
        child["id"]: "cancelling",
        other_tid: "running",
    }
    await swarms.tasks.revisions.request(
        "alice", tid, "Keep the saved user instruction", 1, "pending-user-edit"
    )
    await store.call(
        lambda db: db.execute(
            "UPDATE tasks SET state='cancelled' WHERE id IN (?,?)", (tid, child["id"])
        ),
        write=True,
    )
    await swarms.tasks.revisions.advance()
    assert (await store.call(lambda db: row(db, "SELECT revision FROM tasks WHERE id=?", (tid,))))[
        "revision"
    ] == 1
    await command(swarms, team, "resume_work")
    await swarms.tasks.revisions.advance()
    current = await store.call(
        lambda db: row(db, "SELECT revision,intent_json FROM tasks WHERE id=?", (tid,))
    )
    assert current["revision"] == 2
    assert "Keep the saved user instruction" in json.loads(current["intent_json"])["goal"]
    assert (
        await store.call(lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (other_tid,)))
    )["state"] == "running"


async def test_work_pause_preserves_long_term_goal_authorization(delegated_team):
    from roami_agent.storage.context_admission import assert_context_admitted
    from roami_agent.storage.swarm_delegations import current_delegation

    runtime, service, team, _, turn, binding, spec = delegated_team
    enabled = await service.enable("alice", team["id"], spec, binding=binding, bootstrap=True)
    await command(runtime.swarms, team, "pause_work")
    with pytest.raises(DomainError, match="TURN_INTERRUPTED"):
        await runtime.db.call(lambda db: assert_context_admitted(db, turn))
    current = await runtime.db.call(
        lambda db: current_delegation(db, "alice", team["id"], allow_paused=True)
    )
    assert current["id"] == enabled["delegationId"]
    await runtime.db.call(
        lambda db: db.execute("UPDATE turns SET state='interrupted' WHERE id=?", (turn["id"],)),
        write=True,
    )
    await command(runtime.swarms, team, "resume_work")
    resumed = await service.current("alice", team["id"])
    assert resumed["id"] == enabled["delegationId"]
    assert resumed["source_message_id"] == current["source_message_id"]


@pytest.mark.parametrize("state", ["failed", "waiting_user"])
async def test_pause_does_not_claim_unknown_execution_has_stopped(collaboration, store, state):
    swarms, team = collaboration
    await plan(swarms, team, [item("a")])
    await advance(swarms, team)
    tid = (await swarms.snapshot("alice", team["id"]))["work"][0]["task_id"]
    await store.call(
        lambda db: (
            db.execute("UPDATE tasks SET state=? WHERE id=?", (state, tid)),
            db.execute(
                "UPDATE task_attempts SET state='unknown',result_json=? WHERE task_id=?",
                (json.dumps({"inputStopped": False, "outcomeKnown": False}), tid),
            ),
        ),
        write=True,
    )
    await command(swarms, team, "pause_work")
    view = await swarms.snapshot("alice", team["id"])
    assert view["workPause"]["state"] in {"stopping", "blocked"}
    assert await store.call(lambda db: active_pause(db, team["id"]))
    with pytest.raises(DomainError, match="SWARM_WORK_STOPPING|TASK_OUTCOME_UNRESOLVED"):
        await command(swarms, team, "resume_work")
