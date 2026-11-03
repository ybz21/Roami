import asyncio
import json

import pytest

from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.runner import TaskDispatcher
from roami_agent.dispatch.swarm_plans import SwarmPlans
from roami_agent.dispatch.tasks import Tasks
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.artifact_store import ArtifactStore
from roami_agent.storage.database import event, row, rows
from roami_agent.storage.swarm_repository import dependency_ready
from roami_agent.storage.transcript_repository import message


@pytest.fixture
async def collaboration(store):
    conversations = Conversations(store)
    tasks = Tasks(store, conversations)
    swarms = SwarmPlans(store, tasks, conversations, asyncio.Event())

    class Intake:
        async def submit(self, owner, cid, key, text):
            return await conversations.accept(owner, cid, key, text)

    swarms.chat = Intake()
    created = await swarms.create(
        "alice", {"name": "Build", "goal": "Build and verify outputs", "commandKey": "create"}
    )
    return swarms, created


def item(name, executor="codex", **extra):
    return {
        "member": name,
        "executor": executor,
        "title": "Work " + name,
        "goal": "Implement " + name,
        "acceptance": "Check outputs",
        **extra,
    }


async def plan(swarms, created, items, key="plan"):
    return await swarms.plan(
        "alice",
        created["id"],
        {"commandKey": key, "expectedRevision": created["revision"], "items": items},
    )


async def advance(swarms, created, key="test"):
    await swarms.advance({"id": key, "aggregate_id": created["id"]})


async def test_creation_reuses_main_and_never_spawns_a_commander(collaboration):
    swarms, created = collaboration
    assert (
        await swarms.create(
            "alice", {"name": "Build", "goal": "Build and verify outputs", "commandKey": "create"}
        )
        == created
    )
    assert len(await swarms.conversations.list("alice")) == 1
    value = await swarms.snapshot("alice", created["id"])
    assert value["mainConversationId"] == (await swarms.conversations.main("alice"))["id"]
    assert value["state"] == "planning" and value["posts"][0]["text"] == "Build and verify outputs"
    with pytest.raises(DomainError, match="REQUEST_KEY_CONFLICT"):
        await swarms.create(
            "alice", {"name": "Different", "goal": "Different", "commandKey": "create"}
        )
    with pytest.raises(DomainError, match="SWARM_NOT_FOUND"):
        await swarms.snapshot("bob", created["id"])


async def test_plan_transaction_rejects_cycles_and_stale_revision(collaboration):
    swarms, created = collaboration
    with pytest.raises(DomainError, match="SWARM_DEPENDENCY_CYCLE"):
        await plan(
            swarms,
            created,
            [item("a", dependencies=[{"member": "b"}]), item("b", dependencies=[{"member": "a"}])],
        )
    assert not (await swarms.snapshot("alice", created["id"]))["work"]
    spec = [item("a"), item("b", executor="claude"), item("c", executor="native")]
    first = await plan(swarms, created, spec)
    assert await plan(swarms, created, spec) == first
    with pytest.raises(DomainError, match="SWARM_PLAN_CHANGED"):
        await plan(swarms, created, [item("d")], key="other")


async def test_hard_dependencies_require_verification_and_dispatch_once(collaboration, store):
    swarms, created = collaboration
    await plan(
        swarms,
        created,
        [
            item("a"),
            item("b", executor="claude"),
            item("integration", executor="native", integration=True),
        ],
    )
    await advance(swarms, created)
    view = await swarms.snapshot("alice", created["id"])
    assert [w["task_id"] is not None for w in view["work"]] == [True, True, False]
    assert not any(t["parent_task_id"] for t in await swarms.tasks.list("alice"))
    result = {"state": "succeeded", "summary": "Executor claim only", "checks": []}

    async def verified(task, result):
        return True

    dispatch = TaskDispatcher(store, swarms.tasks, None, verified, None, asyncio.Event(), {})
    for work in view["work"][:2]:
        await swarms.tasks.report("alice", work["task_id"], work["attempt"]["runId"], 1, result)
        await advance(swarms, created)
        assert not (await swarms.snapshot("alice", created["id"]))["work"][2]["task_id"]
        job = await store.call(
            lambda db, w=work: row(
                db,
                "SELECT * FROM jobs WHERE kind='task.verify' AND aggregate_id=?",
                (w["task_id"],),
            )
        )
        await dispatch.verify(job)
    await asyncio.gather(advance(swarms, created, "one"), advance(swarms, created, "two"))
    final = (await swarms.snapshot("alice", created["id"]))["work"][2]
    assert final["task_id"] and len(await swarms.tasks.list("alice")) == 3
    task = await swarms.tasks.get("alice", final["task_id"])
    assert "Verified upstream results" in json.loads(task["task"]["intent_json"])["goal"]


async def test_unknown_result_never_relaunches(collaboration, store):
    swarms, created = collaboration
    await plan(swarms, created, [item("a"), item("integration", integration=True)])
    await advance(swarms, created)
    work = (await swarms.snapshot("alice", created["id"]))["work"][0]
    await store.call(
        lambda db: db.execute(
            "UPDATE task_attempts SET state='unknown' WHERE id=?", (work["attempt"]["runId"],)
        ),
        write=True,
    )
    await advance(swarms, created)
    value = await swarms.snapshot("alice", created["id"])
    assert value["state"] == "blocked" and value["work"][0]["state"] == "unknown"
    assert not value["work"][1]["task_id"] and len(await swarms.tasks.list("alice")) == 1


async def test_dependency_artifact_must_belong_to_the_verified_revision(collaboration, store):
    swarms, created = collaboration
    await plan(swarms, created, [item("a")])
    await advance(swarms, created)
    work = (await swarms.snapshot("alice", created["id"]))["work"][0]
    artifacts = ArtifactStore(store)
    try:
        artifact = await artifacts.put(
            "alice",
            b"verified output",
            task_id=work["task_id"],
            mime_type="text/plain",
            metadata={"runId": work["attempt"]["runId"]},
        )
        await store.call(
            lambda db: db.execute(
                "UPDATE tasks SET state='succeeded' WHERE id=?", (work["task_id"],)
            ),
            write=True,
        )
        dep = {"upstream_id": work["id"], "task_revision": 1, "artifact_id": artifact["id"]}
        assert await store.call(lambda db: dependency_ready(db, dep))
        await store.call(
            lambda db: db.execute("UPDATE tasks SET revision=2 WHERE id=?", (work["task_id"],)),
            write=True,
        )
        assert not await store.call(lambda db: dependency_ready(db, {**dep, "task_revision": 2}))
    finally:
        await artifacts.close()


async def test_original_user_source_survives_unrelated_messages(collaboration, store):
    swarms, created = collaboration
    origin = await store.call(
        lambda db: row(
            db, "SELECT origin_message_id FROM swarm_groups WHERE id=?", (created["id"],)
        )
    )
    await plan(swarms, created, [item("a", executor="native")])
    await swarms.conversations.accept(
        "alice", created["mainConversationId"], "unrelated", "Unrelated request"
    )
    await advance(swarms, created)
    task = (await swarms.tasks.list("alice"))[0]
    assert task["origin_message_id"] == origin["origin_message_id"]


async def test_pause_archive_recovery_preserve_task_identity(collaboration):
    swarms, created = collaboration
    current = await plan(swarms, created, [item("a")])
    paused = await swarms.control(
        "alice",
        created["id"],
        {"action": "pause", "expectedRevision": current["revision"], "commandKey": "pause"},
    )
    await advance(swarms, created)
    assert not await swarms.tasks.list("alice")
    current = await swarms.control(
        "alice",
        created["id"],
        {"action": "resume", "expectedRevision": paused["revision"], "commandKey": "resume"},
    )
    await swarms.recover()
    await advance(swarms, created)
    await swarms.recover()
    await advance(swarms, created)
    assert len(await swarms.tasks.list("alice")) == 1
    await swarms.control(
        "alice",
        created["id"],
        {"action": "archive", "expectedRevision": current["revision"], "commandKey": "archive"},
    )
    assert (await swarms.tasks.list("alice"))[0]["state"] == "queued"
    assert (await swarms.snapshot("alice", created["id"]))["archived"]


async def test_replaying_stop_never_cancels_a_newer_task_revision(collaboration, store):
    swarms, created = collaboration
    current = await plan(swarms, created, [item("a")])
    await advance(swarms, created)
    work = (await swarms.snapshot("alice", created["id"]))["work"][0]
    spec = {"action": "stop", "expectedRevision": current["revision"], "commandKey": "stop"}
    first = await swarms.control("alice", created["id"], spec)
    await store.call(
        lambda db: db.execute(
            "UPDATE tasks SET revision=2,state='running' WHERE id=?", (work["task_id"],)
        ),
        write=True,
    )
    assert await swarms.control("alice", created["id"], spec) == first
    task = await store.call(
        lambda db: row(db, "SELECT state,revision FROM tasks WHERE id=?", (work["task_id"],))
    )
    assert task == {"state": "running", "revision": 2}


def test_http_plan_rejects_malformed_dependencies():
    from pydantic import ValidationError

    from roami_agent.server.swarm_routes import PlanSwarm

    with pytest.raises(ValidationError):
        PlanSwarm.model_validate(
            {
                "commandKey": "plan",
                "expectedRevision": 1,
                "items": [item("a", dependencies=[{"member": []}])],
            }
        )


async def test_group_chat_dedup_and_main_reply(collaboration, store):
    swarms, created = collaboration
    payload = {"commandKey": "message", "text": "Add phone checks"}
    result = await swarms.send("alice", created["id"], payload)
    assert await swarms.send("alice", created["id"], payload) == result

    def reply(db):
        branch = row(
            db,
            "SELECT active_branch_id FROM conversations WHERE id=?",
            (created["mainConversationId"],),
        )["active_branch_id"]
        message(
            db,
            created["mainConversationId"],
            branch,
            "assistant",
            {"text": "Included phone checks"},
            turn_id=result["turnId"],
        )

    await store.call(reply, write=True)
    view = await swarms.snapshot("alice", created["id"])
    assert len(view["posts"]) == 2 and view["mainMessages"][0]["text"] == "Included phone checks"
    with pytest.raises(DomainError, match="REQUEST_KEY_CONFLICT"):
        await swarms.send("alice", created["id"], {**payload, "text": "Changed"})


async def test_worker_posts_require_current_bound_run(collaboration, store):
    swarms, created = collaboration
    await plan(swarms, created, [item("a", executor="native")])
    await advance(swarms, created)
    work = (await swarms.snapshot("alice", created["id"]))["work"][0]
    binding = {
        "taskId": work["task_id"],
        "runId": work["attempt"]["runId"],
        "conversation": "worker",
    }
    await swarms.post(
        "alice", created["id"], {"commandKey": "worker", "text": "Need input"}, binding=binding
    )
    assert (await swarms.snapshot("alice", created["id"]))["posts"][-1]["author"] == "a"
    with pytest.raises(DomainError, match="TASK_RESULT_SUPERSEDED"):
        await swarms.post(
            "alice",
            created["id"],
            {"commandKey": "wrong", "text": "Forged"},
            binding={**binding, "runId": "other"},
        )


async def test_task_completion_has_durable_dependency_update(collaboration, store):
    swarms, created = collaboration
    await plan(swarms, created, [item("a")])
    await advance(swarms, created)
    task = (await swarms.snapshot("alice", created["id"]))["work"][0]["task_id"]
    await store.call(
        lambda db: event(
            db, created["mainConversationId"], "task.succeeded", {"taskId": task}, task_id=task
        ),
        write=True,
    )
    jobs = await store.call(
        lambda db: rows(
            db, "SELECT * FROM jobs WHERE kind='swarm.advance' AND dedupe_key LIKE 'swarm.event:%'"
        )
    )
    assert len(jobs) == 1 and jobs[0]["aggregate_id"] == created["id"]


async def test_dependency_revision_repair_requires_stopped_downstream(collaboration, store):
    swarms, created = collaboration
    await plan(swarms, created, [item("a"), item("final", integration=True)])
    await advance(swarms, created)
    first = (await swarms.snapshot("alice", created["id"]))["work"][0]
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='succeeded' WHERE id=?", (first["task_id"],)),
        write=True,
    )
    await advance(swarms, created)
    before = await swarms.snapshot("alice", created["id"])
    final = before["work"][1]
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='running' WHERE id=?", (final["task_id"],)),
        write=True,
    )
    spec = {
        "commandKey": "rebind",
        "expectedRevision": before["revision"],
        "workId": final["id"],
        "dependencies": [{"member": "a", "revision": 2}],
    }
    with pytest.raises(DomainError, match="SWARM_STOP_REQUIRED"):
        await swarms.dependencies("alice", created["id"], spec)
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='cancelled' WHERE id=?", (final["task_id"],)),
        write=True,
    )
    await swarms.dependencies("alice", created["id"], spec)
    updated = await swarms.snapshot("alice", created["id"])
    assert updated["work"][1]["task_id"] == final["task_id"]
    assert updated["work"][1]["dependencies"][0]["revision"] == 2
    assert updated["work"][1]["state"] == "blocked"


async def test_main_completion_replies_are_in_the_group_chat(collaboration, store):
    swarms, created = collaboration
    await plan(swarms, created, [item("a")])
    await advance(swarms, created)
    first = (await swarms.snapshot("alice", created["id"]))["work"][0]

    async def verified(task, result):
        return True

    dispatcher = TaskDispatcher(store, swarms.tasks, None, verified, None, asyncio.Event(), {})
    await swarms.tasks.report(
        "alice",
        first["task_id"],
        first["attempt"]["runId"],
        1,
        {"state": "succeeded", "summary": "Result", "checks": []},
    )
    job = await store.call(
        lambda db: row(
            db,
            "SELECT * FROM jobs WHERE kind='task.verify' AND aggregate_id=?",
            (first["task_id"],),
        )
    )
    await dispatcher.verify(job)

    def reply(db):
        job = row(
            db,
            "SELECT aggregate_id FROM jobs WHERE kind='turn.run' AND json_extract(payload_json,'$.completion.taskId')=?",
            (first["task_id"],),
        )
        branch = row(
            db,
            "SELECT active_branch_id FROM conversations WHERE id=?",
            (created["mainConversationId"],),
        )["active_branch_id"]
        message(
            db,
            created["mainConversationId"],
            branch,
            "assistant",
            {"text": "Main reviewed the result"},
            turn_id=job["aggregate_id"],
        )

    await store.call(reply, write=True)
    assert "Main reviewed the result" in [
        msg["text"] for msg in (await swarms.snapshot("alice", created["id"]))["mainMessages"]
    ]
