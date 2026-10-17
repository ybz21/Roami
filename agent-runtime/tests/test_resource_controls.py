"""Public takeover cannot acknowledge handoff while a driver still has pending input."""

import httpx
import pytest
from test_browser_driver import BrowserModel
from test_resource_leases import begin, setup

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.server.http import create_app


async def test_pause_releases_only_confirmed_controls_and_resume_requires_a_fresh_lease(store):
    leases, lease, observed, task, run = await setup(store)
    runtime = Runtime(store, BrowserModel())
    try:
        action = await begin(leases, lease, observed, task, run)
        pending = await runtime.controls.pause("alice", lease["id"])
        assert pending["state"] == "pausing" and pending["actionPending"]
        assert not pending["takeoverReady"] and not pending["canResume"]
        with pytest.raises(DomainError, match="RESOURCE_STOP_UNCONFIRMED"):
            await runtime.controls.resume("alice", lease["id"])
        await leases.finish(
            "alice", action["id"], "unknown", {"inputStopped": True, "outcomeKnown": False}
        )
        await runtime.controls.release_ready()
        ready = await runtime.controls.get("alice", lease["id"])
        assert ready["state"] == "paused" and ready["takeoverReady"] and ready["controlReleased"]
        assert ready["leaseEpoch"] > lease["lease_epoch"]
        await runtime.controls.release_ready()
        assert await runtime.controls.get("alice", lease["id"]) == ready
        resumed = await runtime.controls.resume("alice", lease["id"])
        assert resumed["state"] == "idle" and resumed["taskId"] is None
        newer = await leases.claim("alice", task, run, "browser", "fixture:target")
        assert newer["lease_epoch"] > ready["leaseEpoch"]
        with pytest.raises(DomainError, match="RESOURCE_LEASE_STALE"):
            await begin(leases, lease, observed, task, run, "stale-after-resume")
    finally:
        await runtime.close()


async def test_http_controls_are_owner_scoped_and_exclude_typed_input_from_action_details(store):
    leases, lease, observed, task, run = await setup(store)
    runtime = Runtime(store, BrowserModel())
    try:
        action = await begin(leases, lease, observed, task, run)
        await leases.finish(
            "alice",
            action["id"],
            "succeeded",
            {"inputStopped": True, "outcomeKnown": True, "output": "private typed input"},
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
            base_url="http://agent",
        ) as client:
            owner = {"X-Roami-Owner": "alice"}
            response = await client.get("/v1/tasks/" + task + "/resources", headers=owner)
            assert response.status_code == 200
            data = response.json()["data"]
            assert (
                data["resources"][0]["id"] == lease["id"]
                and data["actions"][0]["id"] == action["id"]
            )
            assert "private typed input" not in response.text
            other = {"X-Roami-Owner": "bob"}
            assert (
                await client.get("/v1/tasks/" + task + "/resources", headers=other)
            ).status_code == 404
            assert (
                await client.post("/v1/resources/" + lease["id"] + "/pause", headers=other)
            ).status_code == 404
            paused = await client.post("/v1/resources/" + lease["id"] + "/pause", headers=owner)
            assert paused.status_code == 200 and paused.json()["data"]["takeoverReady"]
            current = await client.get("/v1/resources/" + lease["id"], headers=owner)
            assert current.json()["data"]["state"] == "paused"
            resumed = await client.post("/v1/resources/" + lease["id"] + "/resume", headers=owner)
            assert resumed.status_code == 200 and resumed.json()["data"]["state"] == "idle"
    finally:
        await runtime.close()


async def test_control_listing_includes_claims_before_observation(store):
    _, lease, _, task, _ = await setup(store)
    await store.call(lambda db: db.execute("DELETE FROM resource_observations"), write=True)
    runtime = Runtime(store, BrowserModel())
    try:
        items = (await runtime.controls.task("alice", task))["resources"]
        assert (
            len(items) == 1 and items[0]["id"] == lease["id"] and items[0]["observationId"] is None
        )
        paused = await runtime.controls.pause("alice", lease["id"])
        assert paused["takeoverReady"]
    finally:
        await runtime.close()


async def test_fork_cannot_bypass_parent_takeover_but_an_independent_goal_is_not_blocked(store):
    from test_resource_leases import controller

    from roami_agent.conversation.transcript import Conversations
    from roami_agent.dispatch.tasks import Tasks
    from roami_agent.storage.database import row

    leases, lease, _, parent, _ = await setup(store)
    tasks = Tasks(store, Conversations(store))
    origin = await store.call(
        lambda db: row(db, "SELECT origin_conversation_id FROM tasks WHERE id=?", (parent,))
    )
    child = await tasks.create(
        "alice",
        origin["origin_conversation_id"],
        "Child work",
        key="child-control",
        parent_task_id=parent,
    )

    def running(db):
        db.execute("UPDATE tasks SET state='running' WHERE id=?", (child["id"],))
        db.execute("UPDATE task_attempts SET state='running' WHERE task_id=?", (child["id"],))
        return row(db, "SELECT id FROM task_attempts WHERE task_id=?", (child["id"],))["id"]

    child_run = await store.call(running, write=True)
    child_resource = await leases.claim("alice", child["id"], child_run, "browser", "child-tab")
    await leases.pause("alice", lease["id"])
    with pytest.raises(DomainError, match="RESOURCE_INPUT_PAUSED"):
        await leases.claim("alice", child["id"], child_run, "browser", "replacement-tab")
    runtime = Runtime(store, BrowserModel())
    try:
        assert child_resource["id"] in {
            item["id"] for item in (await runtime.controls.task("alice", parent))["resources"]
        }
        independent, run = await controller(store, key="independent-control")
        await leases.claim("alice", independent, run, "browser", "independent-tab")
    finally:
        await runtime.close()


@pytest.mark.parametrize("kind", ["browser", "desktop"])
async def test_disabled_drivers_still_reconcile_durable_stop_receipts_without_starting_sdk(
    store, kind
):
    import json
    import os

    from test_runtime import until

    from roami_agent.storage.database import row

    leases, lease, observed, task, run = await setup(store)
    if kind == "desktop":
        await store.call(
            lambda db: db.execute("UPDATE resources SET kind='desktop' WHERE id=?", (lease["id"],)),
            write=True,
        )
    action = await begin(leases, lease, observed, task, run)
    runtime = Runtime(store, BrowserModel())

    async def no_cli(*args, **kwargs):
        pytest.fail("Receipt reconciliation started the browser SDK")

    runtime.browser.runner = no_cli
    runtime.desktop.factory = lambda: pytest.fail("Receipt reconciliation connected a desktop")
    root = runtime.browser.receipts if kind == "browser" else runtime.desktop.root
    root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.mkdir(mode=0o700)
    descriptor = os.open(
        root / (action["id"] + ".json"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
    )
    with os.fdopen(descriptor, "w") as file:
        json.dump(
            {
                "version": 1,
                "id": action["id"],
                "payloadHash": action["payload_sha256"],
                "state": "failed",
                "inputStopped": True,
                "outcomeKnown": True,
                "createdMs": 1,
                "updatedMs": 1,
            },
            file,
        )
    await runtime.start()
    try:
        await until(
            store, lambda db: not row(db, "SELECT id FROM resources WHERE owner_task_id=?", (task,))
        )
        assert (
            await store.call(lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (task,)))
        )["state"] == "interrupted"
        assert (
            await store.call(
                lambda db: row(db, "SELECT state FROM resource_actions WHERE id=?", (action["id"],))
            )
        )["state"] == "failed"
    finally:
        await runtime.close()
