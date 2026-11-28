import json
from types import SimpleNamespace

import httpx
import pytest
from test_swarm_provider_generations import prepared, setup_generation

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.swarm_members import MEMBER_MODEL_JOB
from roami_okr.http import create_app

pytest_plugins = ["test_swarm_delegations"]


async def member_with_review(delegated_team, monkeypatch):
    runtime, group, member, migration, _ = await setup_generation(delegated_team, monkeypatch)
    await runtime.swarms.migrate_execution("alice", group["id"], migration)
    await runtime.swarms.plan(
        "alice",
        group["id"],
        {
            "commandKey": "work",
            "expectedRevision": 4,
            "items": [
                {
                    "memberId": member["id"],
                    "member": member["name"],
                    "executor": "claude",
                    "title": "Read references",
                    "goal": "Read existing project references",
                    "acceptance": "Report actual evidence",
                }
            ],
        },
    )

    async def memory(*args):
        return {"content": "Original team memory"}

    monkeypatch.setattr(runtime.swarms, "memory_read", memory)
    await runtime.swarms.control(
        "alice", group["id"], {"commandKey": "resume", "expectedRevision": 5, "action": "resume"}
    )
    await runtime.swarms.advance({"id": "assignment", "aggregate_id": group["id"]})

    def settle(db):
        task = row(db, "SELECT * FROM tasks ORDER BY created_ms LIMIT 1")
        run = row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
        evidence = json.dumps(
            {
                "state": "succeeded",
                "inputStopped": True,
                "outcomeKnown": True,
                "summary": "Retained result",
            }
        )
        db.execute("UPDATE tasks SET state='waiting_user' WHERE id=?", (task["id"],))
        db.execute(
            "UPDATE task_attempts SET state='succeeded',result_json=?,session_id='session-claude',"
            "agent_conversation_id='provider-claude',node_id='local',finished_ms=100 WHERE id=?",
            (evidence, run["id"]),
        )
        db.execute(
            "UPDATE jobs SET state='done' WHERE kind='task.run' AND aggregate_id=?", (task["id"],)
        )
        return {
            "commandKey": "change-original-member",
            "taskId": task["id"],
            "expectedGeneration": 2,
            "expectedTaskRevision": task["revision"],
            "expectedRunId": run["id"],
            "expectedModel": "free",
            "model": "saved-alternate",
        }

    spec = await runtime.db.call(settle, write=True)
    return runtime, group, member, spec


async def selection_job(runtime, task_id):
    return await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind=? AND aggregate_id=?", (MEMBER_MODEL_JOB, task_id)
        )
    )


@pytest.mark.parametrize("allow_metered", [False, True])
async def test_original_member_and_task_survive_a_model_change(
    delegated_team, monkeypatch, allow_metered
):
    runtime, group, member, spec = await member_with_review(delegated_team, monkeypatch)
    if allow_metered:
        spec["allowMetered"] = True
    calls = []

    async def command(sub, *args, spec=None):
        if sub == "prepared":
            return prepared("prepared-role", model="saved-alternate")
        assert sub == "select-model"
        calls.append(spec)
        return {
            **spec,
            "sessionId": "session-claude",
            "providerConversationId": "provider-claude",
            "proof": {"sourceSha256": "b" * 64},
        }

    runtime.member_model_selections.executor = SimpleNamespace(command=command)
    tid = spec["taskId"]
    original_intent = await runtime.db.call(
        lambda db: row(db, "SELECT intent_json FROM tasks WHERE id=?", (tid,))["intent_json"]
    )
    other = await runtime.swarms.create(
        "alice",
        {
            "name": "Other team",
            "goal": "Continue separate work",
            "commandKey": "other-team",
            "target": {"kind": "project", "projectId": "project-b"},
        },
    )
    path = f"/v1/swarms/{group['id']}/members/{member['id']}/model"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        assert (
            await client.post(path, json=spec, headers={"X-Roami-Owner": "bob"})
        ).status_code == 404
        other_path = f"/v1/swarms/{other['id']}/members/{member['id']}/model"
        assert (await client.post(other_path, json=spec)).status_code == 404
        assert (await client.post(path, json={**spec, "expectedRunId": "stale"})).status_code == 409
        queued = await client.post(path, json=spec)
        assert queued.status_code == 202 and queued.json()["data"]["state"] == "pending"
        assert (await client.post(path, json=spec)).json() == queued.json()
        with pytest.raises(DomainError, match="SWARM_MEMBER_MODEL_SELECTION_PENDING"):
            await runtime.tasks.revisions.request("alice", tid, "Review again", 1, "next")
        with pytest.raises(DomainError, match="SWARM_MEMBER_MODEL_SELECTION_PENDING"):
            await runtime.task_sessions.request("alice", tid, 1, spec["expectedRunId"])

        job = await selection_job(runtime, tid)
        assert "swarm.member.select_model" in runtime.scheduler.control_jobs
        await runtime.scheduler._job(job)
        response = (await client.post(path, json=spec)).json()["data"]
        assert response["state"] == "applied"
        assert calls[0].get("allowMetered", False) is allow_metered and len(calls) == 1
        task = await runtime.db.call(lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (tid,)))
        assert task["state"] == "waiting_user" and task["revision"] == 1
        assert task["intent_json"] == original_intent
        team = await runtime.swarms.snapshot("alice", group["id"], include_memory=False)
        changed = next(item for item in team["members"] if item["id"] == member["id"])
        assert changed["provider"]["generation"] == 2
        assert changed["provider"]["sessionId"] == "session-claude"
        assert changed["provider"]["model"] == "saved-alternate"
        assert team["work"][0]["task_id"] == tid

    await runtime.tasks.revisions.request("alice", tid, "Review again", 1, "next")
    await runtime.tasks.revisions.advance()
    next_task = await runtime.db.call(lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (tid,)))
    assert next_task["revision"] == 2
    intent = json.loads(next_task["intent_json"])
    assert intent["model"] == "saved-alternate"
    assert intent["target"]["sessionId"] == "session-claude"
    assert intent["initialIntent"] == json.loads(original_intent)
    old = await runtime.db.call(
        lambda db: row(
            db, "SELECT result_json FROM task_attempts WHERE id=?", (spec["expectedRunId"],)
        )
    )
    assert json.loads(old["result_json"])["summary"] == "Retained result"


async def test_unknown_selection_never_unblocks_the_original_member_without_proof(
    delegated_team, monkeypatch
):
    runtime, group, member, spec = await member_with_review(delegated_team, monkeypatch)
    selector = runtime.member_model_selections
    attempts = []

    async def command(sub, *args, spec=None):
        if sub == "prepared":
            return prepared("prepared-role", model="saved-alternate")
        attempts.append(spec)
        if len(attempts) == 1:
            raise TimeoutError
        return {
            **spec,
            "sessionId": "someone-else",
            "providerConversationId": "provider-claude",
            "proof": {"sourceSha256": "b" * 64},
        }

    selector.executor = SimpleNamespace(command=command)
    await selector.request("alice", group["id"], member["id"], spec)
    for _ in range(2):
        job = await selection_job(runtime, spec["taskId"])
        await selector.advance(job)
        assert (await selector.request("alice", group["id"], member["id"], spec))[
            "state"
        ] == "pending"
        await runtime.db.call(
            lambda db, job_id=job["id"]: db.execute(
                "UPDATE jobs SET available_ms=0 WHERE id=?", (job_id,)
            ),
            write=True,
        )
    assert attempts[0] == attempts[1]
