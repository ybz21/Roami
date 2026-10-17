"""Authenticated task detail retains execution evidence without exposing another owner's data."""

import httpx
from test_resource_leases import controller, setup
from test_runtime import ConversationModel
from test_task_cancellation import task_run

from roami_agent.app import Runtime
from roami_agent.server.http import create_app


async def test_task_detail_has_raw_attempts_child_links_and_steering_receipts(store):
    runtime = Runtime(store, ConversationModel())
    try:
        conversation = await runtime.conversations.create("alice")
        task, run = await task_run(runtime, conversation, "Parent goal")
        child, _ = await task_run(runtime, conversation, "Child goal", task["id"])
        evidence = {"state": "succeeded", "summary": "Independent executor evidence"}
        await runtime.tasks.report("alice", task["id"], run["id"], 1, evidence)
        operation = await runtime.tasks.revisions.request(
            "alice", task["id"], "Additional check", 1, "inspector-steer"
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
            base_url="http://runtime",
        ) as client:
            response = await client.get(
                "/v1/tasks/" + task["id"], headers={"X-Roami-Owner": "alice"}
            )
            assert response.status_code == 200
            detail = response.json()["data"]
            assert detail["task"]["id"] == task["id"] and detail["task"]["revision"] == 1
            assert detail["children"][0]["id"] == child["id"]
            assert detail["attempts"][0]["result"] == evidence
            assert detail["steering"]["operationId"] == operation["operationId"]
            assert not detail["attemptsTruncated"] and not detail["childrenTruncated"]
            assert (
                await client.get("/v1/tasks/" + task["id"], headers={"X-Roami-Owner": "bob"})
            ).status_code == 404
    finally:
        await runtime.close()


async def test_old_task_does_not_offer_a_reused_idle_resource_from_another_goal(store):
    leases, lease, _, first_task, first_run = await setup(store)
    runtime = Runtime(store, ConversationModel())
    try:
        await leases.release("alice", lease["id"], first_task, first_run, lease["lease_epoch"])
        next_task, next_run = await controller(store, key="next-goal")
        reused = await leases.claim("alice", next_task, next_run, "browser", "fixture:target")
        await leases.observe(
            "alice",
            lease["id"],
            next_task,
            next_run,
            reused["lease_epoch"],
            "b" * 64,
            {"title": "New goal"},
        )
        await leases.release("alice", reused["id"], next_task, next_run, reused["lease_epoch"])
        assert (await runtime.controls.task("alice", first_task))["resources"] == []
        assert (await runtime.controls.task("alice", next_task))["resources"][0]["observation"][
            "title"
        ] == "New goal"
    finally:
        await runtime.close()


async def test_handoff_identifies_exact_browser_target_and_hides_creation_context_and_dom(store):
    leases, _, _, task, run = await setup(store)
    runtime = Runtime(store, ConversationModel())
    try:
        context = await leases.claim("alice", task, run, "browser", "browser:instance:context")
        await leases.observe(
            "alice",
            context["id"],
            task,
            run,
            context["lease_epoch"],
            "c" * 64,
            {"browserId": "instance"},
        )
        await leases.release("alice", context["id"], task, run, context["lease_epoch"])
        target = await leases.claim(
            "alice", task, run, "browser", "browser:instance:target:exact-target"
        )
        await leases.observe(
            "alice",
            target["id"],
            task,
            run,
            target["lease_epoch"],
            "d" * 64,
            {
                "title": "Controlled form",
                "url": "https://example.invalid",
                "domText": "private page content",
                "controls": [{"value": "private input"}],
            },
        )
        result = await runtime.controls.task("alice", task)
        assert all(resource["id"] != context["id"] for resource in result["resources"])
        resource = next(item for item in result["resources"] if item["id"] == target["id"])
        assert resource["browserId"] == "instance" and resource["targetId"] == "exact-target"
        assert resource["observation"]["title"] == "Controlled form"
        assert "private page content" not in str(result) and "private input" not in str(result)
    finally:
        await runtime.close()


async def test_acceptance_rejects_stale_revision_attempt_and_pending_continuation(store):
    from roami_agent.storage.database import row

    runtime = Runtime(store, ConversationModel())
    try:
        conversation = await runtime.conversations.create("alice")
        task, run = await task_run(runtime, conversation, "Verify exact result")
        await runtime.tasks.report(
            "alice", task["id"], run["id"], 1, {"state": "succeeded", "summary": "Fixture result"}
        )
        await store.call(
            lambda db: db.execute(
                "UPDATE tasks SET state='waiting_user' WHERE id=?", (task["id"],)
            ),
            write=True,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
            base_url="http://runtime",
            headers={"X-Roami-Owner": "alice"},
        ) as client:
            path = "/v1/tasks/" + task["id"] + "/verify"
            for payload, code in [
                ({"accepted": True, "revision": 2, "runId": run["id"]}, "TASK_REVISION_CHANGED"),
                (
                    {"accepted": True, "revision": 1, "runId": "old-attempt"},
                    "TASK_RESULT_SUPERSEDED",
                ),
            ]:
                response = await client.post(path, json=payload)
                assert response.status_code == 409 and response.json()["error"]["code"] == code
            await runtime.tasks.revisions.request(
                "alice", task["id"], "Continue instead", 1, "pending-acceptance"
            )
            response = await client.post(
                path, json={"accepted": True, "revision": 1, "runId": run["id"]}
            )
            assert (
                response.status_code == 409
                and response.json()["error"]["code"] == "TASK_RESULT_SUPERSEDED"
            )
            assert (
                await store.call(
                    lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],))
                )
            )["state"] == "waiting_user"
    finally:
        await runtime.close()
