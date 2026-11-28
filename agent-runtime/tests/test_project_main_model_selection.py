import asyncio
import copy
from types import SimpleNamespace

import httpx
import pytest
from test_native_main import stopped
from test_project_main_execution import setup_main
from test_runtime import until

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_okr.http import create_app
from roami_okr.intake import wake_project
from roami_okr.main_execution import main_binding
from roami_okr.main_model_selection import pending_model_selection

pytest_plugins = ["test_project_main_wakeup"]

REQUEST = {
    "commandKey": "select-saved-candidate",
    "projectId": "project",
    "expectedGeneration": 1,
    "expectedModel": "free",
    "model": "saved-vision-route",
}


def selected(spec, provider="native-provider"):
    return {
        **spec,
        "sessionId": "native-session",
        "providerConversationId": provider,
        "proof": {"sourceSha256": "a" * 64, "promptId": "fixture-model-control"},
    }


@pytest.mark.parametrize("allow_metered", [False, True])
async def test_daily_turn_waits_for_model_receipt_on_the_same_main(
    wake_runtime, store, monkeypatch, allow_metered
):
    runtime, main, initial, proof, _ = await setup_main(wake_runtime, monkeypatch)
    owner, cid = "alice", main["id"]
    request = {**REQUEST, **({"allowMetered": True} if allow_metered else {})}
    await runtime.main_executions.configure(owner, cid, initial)
    home = await runtime.conversations.main(owner)
    daily = await wake_project(runtime.chat, owner, cid, "project", "today", "Review the board")
    original = await runtime.swarms.create(
        owner,
        {
            "commandKey": "work-team",
            "name": "Original team",
            "goal": "Run the daily checklist",
            "mainConversationId": cid,
            "target": {"kind": "project", "projectId": "project"},
        },
        binding={"conversation": cid, "turnId": daily["turnId"]},
    )
    entered, release = asyncio.Event(), asyncio.Event()
    control_calls, launches = [], []

    async def command(sub, *args, **kwargs):
        if sub == "select-model":
            control_calls.append(kwargs["spec"])
            entered.set()
            await release.wait()
            return selected(kwargs["spec"])
        if sub == "prepared":
            return {**copy.deepcopy(proof), "configuredModel": request["model"]}
        if sub == "launch":
            current = await store.call(lambda db: main_binding(db, owner, cid))
            assert current["model"] == request["model"]
            launches.append(kwargs["spec"])
            return stopped({**current, "binding": proof["sessionBinding"]})
        raise AssertionError(sub)

    runtime.main_executions.executor = SimpleNamespace(command=command)
    path = f"/v1/conversations/{cid}/execution"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://agent",
        headers={"X-Roami-Owner": owner},
    ) as client:
        assert (
            await client.post(path + "/model", json=request, headers={"X-Roami-Owner": "bob"})
        ).status_code == 404
        assert (
            await client.post(f"/v1/conversations/{home['id']}/execution/model", json=request)
        ).status_code == 409
        assert (
            await client.post(path + "/model", json={**request, "expectedGeneration": 2})
        ).status_code == 409
        first = await client.post(path + "/model", json=request)
        assert first.status_code == 202 and first.json()["data"]["state"] == "pending"
        assert (await client.post(path + "/model", json=request)).json() == first.json()
        assert first.json()["data"].get("allowMetered", False) is allow_metered
        assert (
            await client.post(path + "/model", json={**request, "allowMetered": "true"})
        ).status_code == 422
        assert (
            await client.post(path + "/model", json={**request, "allowMetered": not allow_metered})
        ).status_code == 409
        assert (
            await client.post(path + "/model", json={**request, "model": "a-different-route"})
        ).status_code == 409
        await runtime.start()
        await asyncio.wait_for(entered.wait(), timeout=5)
        pending = (await client.get(path)).json()["data"]
        assert pending["model"] == "free" and pending["modelSelection"]["state"] == "pending"
        home_turn = await runtime.chat.submit(owner, home["id"], "home", "Keep working")
        await until(store, lambda db: state(db, home_turn) == "completed")
        assert await store.call(lambda db: state(db, daily)) == "queued"
        assert not launches

        release.set()
        await until(store, lambda db: state(db, daily) == "completed")
        config = (await client.get(path)).json()["data"]
        assert config["generation"] == 1 and config["sessionId"] == "native-session"
        assert config["model"] == request["model"] and "modelSelection" not in config
        assert (await client.post(path + "/model", json=request)).json()["data"][
            "state"
        ] == "applied"
        assert len(control_calls) == len(launches) == 1
        assert control_calls[0].get("allowMetered", False) is allow_metered
        assert launches[0]["sessionId"] == "native-session"
        assert launches[0]["preparedFrom"] == "prepared-main"
        snapshot = await runtime.swarms.snapshot(owner, original["id"], include_memory=False)
        assert snapshot["mainConversationId"] == cid


def state(db, result):
    return row(db, "SELECT state FROM turns WHERE id=?", (result["turnId"],))["state"]


async def test_timeout_and_wrong_native_identity_keep_original_queued_scope(
    wake_runtime, store, monkeypatch
):
    runtime, main, initial, proof, _ = await setup_main(wake_runtime, monkeypatch)
    owner, cid = "alice", main["id"]
    await runtime.main_executions.configure(owner, cid, initial)
    await runtime.main_model_selections.request(owner, cid, REQUEST)
    daily = await wake_project(runtime.chat, owner, cid, "project", "today", "Existing daily work")
    calls = []

    async def command(sub, *args, **kwargs):
        if sub == "prepared":
            return {**copy.deepcopy(proof), "configuredModel": REQUEST["model"]}
        assert sub == "select-model"
        calls.append(kwargs["spec"])
        if len(calls) == 1:
            raise TimeoutError
        if len(calls) == 3:
            return selected({**kwargs["spec"], "allowMetered": True})
        return selected(kwargs["spec"], "other" if len(calls) == 2 else "native-provider")

    runtime.main_executions.executor = SimpleNamespace(command=command)
    for _ in range(3):
        job = await store.call(lambda db: pending_model_selection(db, cid))
        await runtime.main_model_selections.advance(job)
        turn_job = await store.call(
            lambda db: row(db, "SELECT * FROM jobs WHERE aggregate_id=?", (daily["turnId"],))
        )
        assert await runtime.mailbox.claim(turn_job) is None
        assert (await runtime.main_model_selections.request(owner, cid, REQUEST))[
            "state"
        ] == "pending"
        await store.call(
            lambda db, job_id=job["id"]: db.execute(
                "UPDATE jobs SET available_ms=0 WHERE id=?", (job_id,)
            ),
            write=True,
        )
    await runtime.main_model_selections.advance(job)
    assert len(calls) == 4 and all(call == calls[0] for call in calls)
    assert (await runtime.main_model_selections.request(owner, cid, REQUEST))["state"] == "applied"
    assert await store.call(lambda db: state(db, daily)) == "queued"


async def test_confirmed_refusal_before_input_releases_existing_model(
    wake_runtime, store, monkeypatch
):
    runtime, main, initial, _, _ = await setup_main(wake_runtime, monkeypatch)
    owner, cid = "alice", main["id"]
    await runtime.main_executions.configure(owner, cid, initial)
    await runtime.main_model_selections.request(owner, cid, REQUEST)

    async def command(sub, *args, **kwargs):
        assert sub == "select-model"
        raise DomainError("SESSION_MODEL_SELECTION_TARGET_UNCONFIRMED", 409)

    runtime.main_executions.executor = SimpleNamespace(command=command)
    job = await store.call(lambda db: pending_model_selection(db, cid))
    await runtime.main_model_selections.advance(job)
    assert await store.call(lambda db: pending_model_selection(db, cid)) is None
    rejected = await runtime.main_model_selections.request(owner, cid, REQUEST)
    assert rejected["state"] == "rejected"
    assert rejected["reason"] == "SESSION_MODEL_SELECTION_TARGET_UNCONFIRMED"
    assert (await store.call(lambda db: main_binding(db, owner, cid)))["model"] == "free"
