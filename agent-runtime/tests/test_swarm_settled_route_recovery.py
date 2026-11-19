import copy
import json
from types import SimpleNamespace

import pytest
from test_native_main import stopped
from test_swarm_coordination import claim, queue
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_coordination import delegated_team as delegated_team_fixture
from test_swarm_provider_generations import prepared
from test_swarm_result_observations import observations, report

from roami_agent.executors.targets import TargetDirectory
from roami_agent.protocol.identity import now_ms
from roami_agent.storage.database import row
from roami_agent.storage.swarm_coordination import admitted_batch

coordination = coordination_fixture
delegated_team = delegated_team_fixture


async def query_job(runtime, batch):
    return await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?", (batch["turnId"],)
        )
    )


@pytest.fixture
async def failed_route(coordination, monkeypatch):
    runtime, _, team, _, _, actor = coordination
    proof = prepared("prepared-original", session="original-main-session")
    binding = {"session_id": proof["sessionId"], "binding": proof["sessionBinding"]}
    launches = []

    async def command(sub, *args, spec=None):
        if sub == "prepared":
            assert args == ("--key", proof["launchKey"])
            return copy.deepcopy(proof)
        assert sub == "launch"
        launches.append(spec)
        if len(launches) > 1:
            return stopped(binding)
        proof["routeRefusal"] = {
            "launchKey": spec["key"],
            "code": "CLAUDE_COMPACTION_FAILED",
            "stopEvidenceSha256": "a" * 64,
            "finishedMs": now_ms(),
        }
        # The old runtime saw a terminal native failure but returned a generic host error.
        return stopped(binding, state="failed")

    async def workspace(self, project_id):
        assert project_id == "project-a"
        return {"directory": proof["sessionBinding"]["directory"]}

    async def control(action):
        state = await runtime.swarms.snapshot("alice", team["id"], include_memory=False)
        await runtime.swarms.control(
            "alice",
            team["id"],
            {"action": action, "commandKey": action, "expectedRevision": state["revision"]},
        )

    monkeypatch.setattr(TargetDirectory, "project_workspace", workspace)
    runtime.main_executions.executor = SimpleNamespace(command=command)
    await control("pause")
    await runtime.main_executions.configure(
        "alice",
        team["mainConversationId"],
        {
            "projectId": "project-a",
            "commandKey": "prepared-original",
            "expectedGeneration": 0,
            "executor": "claude",
            "model": "free",
            "preparedLaunchKey": proof["launchKey"],
        },
    )
    await control("resume")
    await report(runtime, actor)
    batch = await queue(runtime, team)
    await runtime.scheduler._job(await query_job(runtime, batch))
    assert (await query_job(runtime, batch))["state"] == "failed"
    before = await observations(runtime)
    assert len(before) == 1
    return runtime, team, batch, proof, launches, before


async def test_restart_requeues_legacy_refusal_and_keeps_original_receipt(
    failed_route, monkeypatch
):
    runtime, team, batch, proof, launches, before = failed_route
    await runtime.main_executions.recover_settled_route_waits()
    job = await query_job(runtime, batch)
    assert job["state"] == "queued"
    assert json.loads(job["payload_json"]) == {
        "coordinationBatchId": batch["batchId"],
        "nativeRouteRetry": 1,
    }
    assert len(launches) == 1 and await observations(runtime) == before
    await runtime.main_executions.recover_settled_route_waits()
    assert await query_job(runtime, batch) == job
    monkeypatch.setattr("roami_agent.conversation.mailbox.now_ms", lambda: job["available_ms"])
    turn = await claim(runtime, batch)
    original = await runtime.db.call(lambda db: admitted_batch(db, "alice", turn["id"]))
    assert original["results"][0]["executionReceipt"]["receiptId"] == before[0]["receipt_id"]
    assert await runtime.run_turn(turn, "main") == "Actual native answer"
    assert launches[-1]["sessionId"] == launches[0]["sessionId"] == proof["sessionId"]
    assert launches[-1]["key"].endswith(":retry-1")
    assert (await runtime.swarms.snapshot("alice", team["id"], include_memory=False))[
        "mainState"
    ] == "completed"


@pytest.mark.parametrize(
    "change", ["foreign_turn", "wrong_provider", "untyped", "newer_turn", "stop"]
)
async def test_stale_or_unproven_legacy_refusal_stays_terminal(failed_route, change):
    runtime, team, batch, proof, launches, _ = failed_route
    if change == "foreign_turn":
        proof["routeRefusal"]["launchKey"] = "project-main:" + "0" * 32 + ":" + "1" * 24
    if change == "wrong_provider":
        proof["sessionBinding"]["providerConversationId"] = "foreign"
    if change == "untyped":
        proof["routeRefusal"]["code"] = "PROJECT_MAIN_EXECUTION_FAILED"
    if change == "newer_turn":
        await runtime.conversations.accept(
            "alice", team["mainConversationId"], "new", "New request"
        )
    if change == "stop":
        await runtime.db.call(
            lambda db: db.execute(
                "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) "
                "VALUES('stop','control.stop','stop','stop',?,'done',0)",
                (json.dumps({"turnId": batch["turnId"]}),),
            ),
            write=True,
        )
    await runtime.main_executions.recover_settled_route_waits()
    assert (await query_job(runtime, batch))["state"] == "failed"
    assert len(launches) == 1
