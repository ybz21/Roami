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


async def test_native_task_status_finds_only_current_run_review_artifacts(native_review):
    runtime, _, context, args, artifact = native_review
    task_id, run_id = args["taskId"], args["runId"]
    recover = await runtime.main_capabilities.call(
        "swarm_verify",
        request(context, {**args, "artifactIds": []}, "missing-artifact-ids"),
        "alice",
    )
    assert recover["result"]["error"] == "SWARM_DELIVERABLE_EVIDENCE_REQUIRED"
    assert "task_status" in recover["result"]["recovery"]
    for source, associated_run in [("workspace_output", "old-run"), ("native_result", run_id)]:
        await runtime.artifacts.put(
            "alice",
            b"Not a current deliverable",
            name=source + ".txt",
            mime_type="text/plain",
            task_id=task_id,
            metadata={"source": source, "runId": associated_run},
        )
    old_status = await runtime.main_capabilities.call(
        "task_status", request(context, {}, "list-status"), "alice"
    )
    assert all("reviewEvidence" not in item for item in old_status["result"])
    status = await runtime.main_capabilities.call(
        "task_status", request(context, {"taskId": task_id}, "status-evidence"), "alice"
    )
    assert status["state"] == "succeeded"
    detail = status["result"][0]
    assert detail["revision"] == args["revision"] and detail["latestAttempt"]["runId"] == run_id
    assert "executorResult" not in detail
    assert detail["reviewEvidence"] == {
        "swarmId": args["swarmId"],
        "externalActionRequiresUser": False,
        "artifacts": [
            {
                "id": artifact["id"],
                "name": "report.json",
                "mimeType": "application/json",
                "sizeBytes": 16,
            }
        ],
        "hasMore": False,
    }

    for num in range(8):
        await runtime.artifacts.put(
            "alice",
            b"Supplemental evidence",
            name=f"support-{num}.txt",
            mime_type="text/plain",
            task_id=task_id,
            metadata={"source": "workspace_output", "runId": run_id},
        )
    bounded = await runtime.main_capabilities.call(
        "task_status", request(context, {"taskId": task_id}, "status-evidence-bounded"), "alice"
    )
    evidence = bounded["result"][0]["reviewEvidence"]
    assert len(evidence["artifacts"]) == 8 and evidence["hasMore"]
    assert artifact["id"] in {item["id"] for item in evidence["artifacts"]}

    # An admitted identity and visible metadata still cannot satisfy the acceptance gate.
    before_read = await runtime.main_capabilities.call(
        "swarm_verify", request(context, args, "visible-artifact-unread"), "alice"
    )
    assert before_read["result"]["error"] == "SWARM_ARTIFACT_REVIEW_REQUIRED"
    shown = next(item for item in evidence["artifacts"] if item["name"] == "report.json")
    read = await runtime.main_capabilities.call(
        "read",
        request(
            context,
            {"path": "artifact://" + shown["id"], "offset": 0, "limit": 8000},
            "read-evidence",
        ),
        "alice",
    )
    assert read["result"]["text"] == '{"observed": 3}\n' and read["result"]["nextRead"] is None
    done = await runtime.main_capabilities.call(
        "swarm_verify",
        request(context, {**args, "artifactIds": [shown["id"]]}, "verify-retained-evidence"),
        "alice",
    )
    assert done["state"] == "succeeded"


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
