import copy
import json

import httpx
from test_swarm_member_model_selection import member_with_review
from test_swarm_provider_generations import prepared

from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.storage.database import row
from roami_okr.http import create_app

pytest_plugins = ["test_swarm_delegations"]


async def test_original_member_recovery_preserves_a_stopped_run_and_continues_its_task(
    delegated_team, monkeypatch
):
    runtime, team, member, selection = await member_with_review(delegated_team, monkeypatch)
    spec = {**selection, "commandKey": "recover-role", "preparedLaunchKey": "recovered-role"}
    tid, rid = spec["taskId"], spec["expectedRunId"]

    def original(db):
        prior = row(db, "SELECT binding_json FROM swarm_member_provider_generations")
        binding = {
            **json.loads(prior["binding_json"]),
            "providerHome": "/project/claude",
            "providerHomeProof": "same-home",
        }
        db.execute(
            "UPDATE swarm_member_provider_generations SET binding_json=?", (json.dumps(binding),)
        )
        run = row(db, "SELECT * FROM task_attempts WHERE id=?", (rid,))
        return binding, run

    old_binding, old_run = await runtime.db.call(original, write=True)
    recovery = prepared("recovered-role", session="replacement-session", model=spec["model"])
    recovery.update(recoveredFrom=old_run["launch_id"])
    recovery["sessionBinding"].update(
        providerHome=old_binding["providerHome"], providerHomeProof=old_binding["providerHomeProof"]
    )
    status = {
        "session": old_run["session_id"],
        "sessionBinding": old_binding,
        "state": old_run["state"],
        "result": json.loads(old_run["result_json"]),
    }
    reads = []

    async def command(self, verb, *args):
        reads.append((verb, *args))
        if verb == "prepared":
            assert args == ("--key", recovery["launchKey"])
            return copy.deepcopy(recovery)
        assert verb == "status" and args == ("--key", old_run["launch_id"])
        return copy.deepcopy(status)

    monkeypatch.setattr(CodingExecutor, "command", command)
    path = f"/v1/swarms/{team['id']}/members/{member['id']}/execution"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        assert (
            await client.put(path, json=spec, headers={"X-Roami-Owner": "bob"})
        ).status_code == 404
        assert (await client.put(path, json={**spec, "expectedRunId": "stale"})).status_code == 409
        assert not reads
        expected_provider = recovery["sessionBinding"]["providerConversationId"]
        recovery["sessionBinding"]["providerConversationId"] = "another-provider"
        assert (await client.put(path, json=spec)).status_code == 409
        recovery["sessionBinding"]["providerConversationId"] = expected_provider
        status["result"]["outcomeKnown"] = False
        assert (await client.put(path, json=spec)).status_code == 409
        status["result"]["outcomeKnown"] = True
        updated = await client.put(path, json=spec)
        assert updated.status_code == 200, updated.text
        assert updated.json()["data"]["sessionId"] == "replacement-session"
        assert updated.json()["data"]["generation"] == 3
        count = len(reads)
        assert (await client.put(path, json=spec)).json() == updated.json()
        assert len(reads) == count

    current = await runtime.swarms.snapshot("alice", team["id"], include_memory=False)
    assert current["paused"] is False
    assert current["members"][0]["provider"]["generation"] == 3
    assert current["work"][0]["task_id"] == tid
    assert (
        await runtime.db.call(lambda db: row(db, "SELECT * FROM task_attempts WHERE id=?", (rid,)))
        == old_run
    )
    await runtime.tasks.revisions.request("alice", tid, "Finish existing work", 1, "continue")
    await runtime.tasks.revisions.advance()
    next_task = await runtime.db.call(lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (tid,)))
    assert next_task["revision"] == 2
    intent = json.loads(next_task["intent_json"])
    assert intent["target"] == {
        "kind": "session",
        "sessionId": "replacement-session",
        "nodeId": "local",
        "providerLaunchKey": "recovered-role",
    }
    assert intent["model"] == spec["model"]
