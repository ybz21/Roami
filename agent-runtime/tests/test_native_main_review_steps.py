"""Native Main retains the hosted read-before-verify gate across signed steps."""

import asyncio

import pytest
from test_native_main_capabilities import group_for, request
from test_native_main_capabilities import native_main as native_main_fixture

from roami_agent.storage.database import row

native_main = native_main_fixture
pytest_plugins = ["test_project_main_wakeup"]


@pytest.fixture
async def native_review(native_main):
    runtime, main, turn, context = native_main
    group = await group_for(runtime, main, turn)
    registered = await runtime.main_capabilities.call(
        "swarm_members_register",
        request(
            context,
            {
                "swarmId": group["id"],
                "expectedRevision": 1,
                "members": [{"name": "writer", "executor": "native", "duty": "Write report"}],
            },
            "register",
        ),
        "alice",
    )
    member = registered["result"]["members"][0]
    planned = await runtime.main_capabilities.call(
        "swarm_plan",
        request(
            context,
            {
                "swarmId": group["id"],
                "expectedRevision": 2,
                "items": [
                    {
                        "memberId": member["id"],
                        "member": "writer",
                        "executor": "native",
                        "title": "Report",
                        "goal": "Write an independently reviewable report",
                        "acceptance": "Main reads and checks the actual report",
                        "deliverables": [
                            {
                                "kind": "artifact",
                                "description": "JSON report",
                                "mimeType": "application/json",
                            }
                        ],
                    }
                ],
            },
            "plan",
        ),
        "alice",
    )
    assert planned["state"] == "succeeded", planned
    await runtime.swarms.advance({"id": "advance", "aggregate_id": group["id"]})
    work = (await runtime.swarms.snapshot("alice", group["id"]))["work"][0]
    task, run = work["task_id"], work["attempt"]["runId"]
    artifact = await runtime.artifacts.put(
        "alice",
        b'{"observed": 3}\n',
        mime_type="application/json",
        name="report.json",
        task_id=task,
        metadata={"source": "workspace_output", "runId": run},
    )
    await runtime.tasks.report(
        "alice",
        task,
        run,
        1,
        {
            "state": "succeeded",
            "summary": "Report prepared",
            "inputStopped": True,
            "outcomeKnown": True,
        },
    )
    job = await runtime.db.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='task.verify' AND aggregate_id=?", (task,)
        )
    )
    await runtime.dispatch.verify(job)
    args = {
        "swarmId": group["id"],
        "taskId": task,
        "revision": 1,
        "runId": run,
        "accepted": True,
        "checks": "Read complete report and checked observed value",
        "artifactIds": [artifact["id"]],
    }
    return runtime, turn, context, args, artifact


async def test_native_review_requires_prior_read_and_replay_creates_no_step(native_review):
    runtime, turn, context, args, artifact = native_review
    missing = await runtime.main_capabilities.call(
        "swarm_verify", request(context, args, "missing"), "alice"
    )
    assert missing["result"]["error"] == "SWARM_ARTIFACT_REVIEW_REQUIRED"
    read_request = request(context, {"path": "artifact://" + artifact["id"]}, "read")
    read = await runtime.main_capabilities.call("read", read_request, "alice")
    assert read["state"] == "succeeded" and read["result"]["textAvailable"]

    async def count():
        return await runtime.db.call(
            lambda db: db.execute(
                "SELECT count(*) FROM messages WHERE turn_id=?", (turn["id"],)
            ).fetchone()[0]
        )

    before = await count()
    assert await runtime.main_capabilities.call("read", read_request, "alice") == read
    assert await count() == before
    result = await runtime.main_capabilities.call(
        "swarm_verify", request(context, args, "verified"), "alice"
    )
    assert result["state"] == "succeeded", result
    assert (await runtime.tasks.get("alice", args["taskId"]))["task"]["state"] == "succeeded"


async def test_native_parallel_read_cannot_satisfy_verification(native_review, monkeypatch):
    runtime, _, context, args, artifact = native_review
    entered, release = asyncio.Event(), asyncio.Event()
    original = runtime.artifacts.read_page

    async def delayed(*positional, **keywords):
        entered.set()
        await release.wait()
        return await original(*positional, **keywords)

    monkeypatch.setattr(runtime.artifacts, "read_page", delayed)
    pending = asyncio.create_task(
        runtime.main_capabilities.call(
            "read",
            request(
                context,
                {"path": "artifact://" + artifact["id"], "offset": 0, "limit": 16000},
                "pending-read",
            ),
            "alice",
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        result = await runtime.main_capabilities.call(
            "swarm_verify", request(context, args, "parallel"), "alice"
        )
        assert result["result"]["error"] == "SWARM_ARTIFACT_REVIEW_REQUIRED"
    finally:
        release.set()
        await pending
    result = await runtime.main_capabilities.call(
        "swarm_verify", request(context, args, "after-read"), "alice"
    )
    assert result["state"] == "succeeded", result
