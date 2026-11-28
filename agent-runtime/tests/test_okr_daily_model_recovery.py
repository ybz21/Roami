import copy
import json
from types import SimpleNamespace

import httpx
import pytest
from test_native_main import stopped
from test_swarm_delegations import delegated_team as delegated_team_fixture
from test_swarm_settled_route_recovery import coordination as coordination_fixture
from test_swarm_settled_route_recovery import failed_route as failed_route_fixture
from test_swarm_settled_route_recovery import query_job

from roami_agent.storage.database import event, row
from roami_agent.storage.swarm_coordination import admitted_batch
from roami_agent.storage.swarm_daily_goal import date_slot
from roami_okr.http import create_app
from roami_okr.main_model_selection import pending_model_selection

coordination = coordination_fixture
failed_route = failed_route_fixture
delegated_team = delegated_team_fixture


@pytest.fixture
async def changed_model(failed_route):
    runtime, team, daily, proof, launches, _ = failed_route
    cid = team["mainConversationId"]
    first = launches[0]
    actual_binding = {"session_id": proof["sessionId"], "binding": proof["sessionBinding"]}
    calls, status_by_key = [], {}
    retry = await runtime.chat.submit("alice", cid, "later-failed", "Recheck the original work")
    switched = False

    async def command(sub, *args, spec=None):
        calls.append(sub)
        if sub == "prepared":
            return {**copy.deepcopy(proof), "configuredModel": "alternate" if switched else "free"}
        if sub == "launch":
            if switched:
                return stopped(actual_binding)
            launches.append(spec)
            return stopped(actual_binding, state="failed")
        if sub == "status":
            return status_by_key[args[1]]
        if sub == "select-model":
            return {
                **spec,
                "sessionId": proof["sessionId"],
                "providerConversationId": proof["sessionBinding"]["providerConversationId"],
                "proof": {"sourceSha256": "a" * 64},
            }
        raise AssertionError(sub)

    runtime.main_executions.executor = SimpleNamespace(command=command)
    await runtime.scheduler._job(await query_job(runtime, retry))
    assert (await query_job(runtime, retry))["state"] == "failed"

    def old_receipts(db):
        batch = row(db, "SELECT * FROM swarm_coordination_batches WHERE id=?", (daily["batchId"],))
        marker = date_slot(batch["delegation_id"], timezone="Asia/Shanghai", slot="morning")
        db.execute(
            "UPDATE jobs SET payload_json=json_set(payload_json,'$.dailySlot',json(?)) "
            "WHERE kind='turn.run' AND aggregate_id=?",
            (json.dumps(marker), daily["turnId"]),
        )
        for source, launch in ((daily, first), (retry, launches[1])):
            t = row(db, "SELECT * FROM turns WHERE id=?", (source["turnId"],))
            epoch = t["lease_epoch"]
            event(
                db,
                cid,
                "turn.native_delivery",
                {"leaseEpoch": epoch, "state": "closed"},
                key=f"native-delivery:{launch['key']}:{epoch}:closed",
                turn_id=t["id"],
            )
            out = {**stopped(actual_binding, state="failed"), "state": "failed"}
            out["result"].update(
                errorCode="MODEL_HTTP_400", stopEvidenceSha256="b" * 64, finishedMs=t["finished_ms"]
            )
            status_by_key[launch["key"]] = out
        return marker

    marker = await runtime.db.call(old_receipts, write=True)
    switch = {
        "commandKey": "switch-original-main",
        "projectId": "project-a",
        "expectedGeneration": 1,
        "expectedModel": "free",
        "model": "alternate",
    }
    await runtime.main_model_selections.request("alice", cid, switch)
    job = await runtime.db.call(lambda db: pending_model_selection(db, cid))
    switched = True
    await runtime.main_model_selections.advance(job)
    assert (await runtime.main_model_selections.request("alice", cid, switch))["state"] == "applied"
    return runtime, cid, daily, marker, status_by_key, calls


def request(daily):
    return {
        "commandKey": "same-morning-recovery",
        "projectId": "project-a",
        "modelCommandKey": "switch-original-main",
        "turnId": daily["turnId"],
    }


async def test_retry_reuses_the_scheduled_slot_after_a_later_failed_turn(
    changed_model, monkeypatch
):
    runtime, cid, daily, marker, statuses, calls = changed_model
    path = f"/v1/conversations/{cid}/execution/retry-daily"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        assert (
            await client.post(path, json=request(daily), headers={"X-Roami-Owner": "bob"})
        ).status_code == 404
        response = await client.post(path, json=request(daily))
        assert response.status_code == 202, response.text
        result = response.json()["data"]
        assert result == {**daily, "dailySlot": marker, "model": "alternate", "state": "queued"}
        assert (await client.post(path, json=request(daily))).json() == response.json()
        assert calls.count("status") == len(statuses) == 2
    job = await query_job(runtime, daily)
    monkeypatch.setattr("roami_agent.conversation.mailbox.now_ms", lambda: job["available_ms"])
    active = await runtime.mailbox.claim(job)
    assert active["id"] == daily["turnId"] and active["native_route_retry"] == 1
    batch = await runtime.db.call(lambda db: admitted_batch(db, "alice", active["id"]))
    assert batch["id"] == daily["batchId"]
    assert batch["dailySlot"] == marker
    _, prompt = await runtime.loop.context.build(active, "Recover the original slot.", [], None)
    assert any("Recheck the original work" in str(message.get("content", "")) for message in prompt)
    assert await runtime.run_turn(active, "main") == "Actual native answer"


@pytest.mark.parametrize(
    "case", ["unknown-stop", "newer-success", "newer-different-model", "other-switch"]
)
async def test_retry_fails_closed_if_the_original_batch_is_no_longer_safe(changed_model, case):
    runtime, cid, daily, _, statuses, _ = changed_model
    body = request(daily)
    later = next(key for key in statuses if key.split(":")[1] != daily["turnId"])
    later_id = later.split(":")[1]
    if case == "unknown-stop":
        statuses[later]["result"]["outcomeKnown"] = False
    elif case == "newer-success":
        await runtime.db.call(
            lambda db: db.execute("UPDATE turns SET state='completed' WHERE id=?", (later_id,)),
            write=True,
        )
    elif case == "newer-different-model":
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE prompt_manifests SET model_key='changed' WHERE turn_id=?", (later_id,)
            ),
            write=True,
        )
    else:
        body["modelCommandKey"] = "not-applied"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        response = await client.post(f"/v1/conversations/{cid}/execution/retry-daily", json=body)
        assert response.status_code == 409
    assert (await query_job(runtime, daily))["state"] == "failed"


async def test_new_message_after_retry_admission_invalidates_its_frozen_context(
    changed_model, monkeypatch
):
    runtime, cid, daily, _, _, calls = changed_model
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://agent",
        headers={"X-Roami-Owner": "alice"},
    ) as client:
        recovery = await client.post(
            f"/v1/conversations/{cid}/execution/retry-daily", json=request(daily)
        )
        assert recovery.status_code == 202, recovery.text
    await runtime.conversations.accept("alice", cid, "new-directive", "Keep publication paused")
    job = await query_job(runtime, daily)
    monkeypatch.setattr("roami_agent.conversation.mailbox.now_ms", lambda: job["available_ms"])
    assert await runtime.mailbox.claim(job) is None
    error = await runtime.db.call(
        lambda db: row(
            db,
            "SELECT kind,payload_json FROM events WHERE turn_id=? ORDER BY id DESC",
            (daily["turnId"],),
        )
    )
    assert error["kind"] == "turn.interrupted"
    assert json.loads(error["payload_json"])["error"] == "SWARM_COORDINATION_CONTEXT_CHANGED"
    assert calls.count("launch") == 1
