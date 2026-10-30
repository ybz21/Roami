"""Retained provider reports are useful without pretending an unknown task is complete."""

import copy
import io
import json
import os
from pathlib import Path

import pytest
from test_routing_policy import setup
from test_task_delivery_benchmark import admit

from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


async def reported_task(store, tmp_path):
    from roami_agent.improvement.evaluation.case_catalog import case_resource

    recipe = json.loads(
        Path(
            os.environ.get("ROAMI_CASE61_INPUT", case_resource("MECH-VD03", "input/incident.json"))
        ).read_text()
    )
    paths = [Path(name) for name in recipe["reported_outputs"]]
    assert all(not path.is_absolute() and ".." not in path.parts for path in paths)
    workspace = tmp_path / "workspace"
    page = workspace / paths[0].parent
    page.mkdir(parents=True)
    assert [p.name for p in paths] == ["index.html", "shot.png"]
    (page / "index.html").write_text("<!doctype html><title>Research report</title>")
    from PIL import Image

    picture = io.BytesIO()
    Image.new("RGB", (2, 2)).save(picture, format="PNG")
    (page / "shot.png").write_bytes(picture.getvalue())
    (workspace / "unrelated.txt").write_text("Must not be collected")
    runtime, _, _, _, binding = await setup(store, settings=Settings(coding_directory=workspace))
    task = await admit(
        runtime,
        binding,
        "Create a research page",
        "reported-page",
        executor="claude",
        target={"kind": "new_session", "directory": str(workspace)},
    )
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='running' WHERE id=?", (task["id"],)),
        write=True,
    )
    run = await store.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    receipt = {
        "state": "unknown",
        "session": "reported-session",
        "sessionBinding": {"id": "reported-session", "providerConversationId": "provider-report"},
        "workspace": {"directory": str(workspace)},
        "progress": {
            "source": "provider_transcript",
            "summary": "Created [page](index.html) and `shot.png`",
            "directory": str(page),
            "providerConversationId": "provider-report",
            "promptId": "task-prompt",
            "sourceDigest": "a" * 64,
            "observedMs": 123456,
        },
    }
    return runtime, task, run, receipt, page


async def test_unknown_task_retains_reported_files_without_fabricating_completion(store, tmp_path):
    runtime, task, run, receipt, page = await reported_task(store, tmp_path)
    executor = CodingExecutor(store, Settings())
    try:
        await executor.record(task, run, receipt)
        detail = await runtime.tasks.get("alice", task["id"])
        assert detail["task"]["state"] == "running"
        attempt = detail["attempts"][0]
        assert attempt["state"] == "unknown" and attempt["finishedMs"] is None
        assert (
            attempt["result"] is None
            and attempt["progress"]["summary"] == receipt["progress"]["summary"]
        )
        artifacts = detail["delivery"]["artifacts"]
        assert {artifact["name"] for artifact in artifacts} == {"index.html", "shot.png"}
        assert all(artifact["metadata"]["provisional"] for artifact in artifacts)
        for artifact in artifacts:
            assert (await runtime.artifacts.read("alice", artifact["id"]))[1] == (
                page / artifact["name"]
            ).read_bytes()
        assert not detail["delivery"]["unavailable"]
        assert (
            await store.call(
                lambda db: db.execute(
                    "SELECT COUNT(*) FROM jobs WHERE kind='task.verify' AND aggregate_id=?",
                    (task["id"],),
                ).fetchone()[0]
            )
            == 0
        )
    finally:
        await runtime.close()


async def test_reported_files_are_idempotent_and_deleted_files_do_not_reappear(store, tmp_path):
    runtime, task, run, receipt, _ = await reported_task(store, tmp_path)
    executor = CodingExecutor(store, Settings())
    try:
        await executor.record(task, run, receipt)
        first = (await runtime.tasks.get("alice", task["id"]))["delivery"]["artifacts"]
        await executor.record(task, run, receipt)
        second = (await runtime.tasks.get("alice", task["id"]))["delivery"]["artifacts"]
        assert [a["id"] for a in first] == [a["id"] for a in second]
        assert (
            await store.call(
                lambda db: db.execute(
                    "SELECT COUNT(*) FROM events WHERE task_id=? AND kind='task.execution_progress'",
                    (task["id"],),
                ).fetchone()[0]
            )
            == 1
        )
        await runtime.artifacts.delete("alice", first[0]["id"])
        after = (await runtime.tasks.get("alice", task["id"]))["delivery"]["artifacts"]
        assert len(after) == 1 and after[0]["id"] != first[0]["id"]
        with pytest.raises(DomainError, match="TASK_NOT_FOUND"):
            await runtime.tasks.get("bob", task["id"])
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "fault", ["provider", "session", "directory", "digest", "summary", "source"]
)
async def test_unbound_reported_progress_is_rejected_without_retaining_files(
    store, tmp_path, fault
):
    runtime, task, run, original, _ = await reported_task(store, tmp_path)
    receipt = copy.deepcopy(original)
    if fault == "provider":
        receipt["progress"]["providerConversationId"] = "another-provider"
    elif fault == "session":
        receipt["session"] = "another-session"
    elif fault == "directory":
        receipt["progress"]["directory"] = str(tmp_path)
    elif fault == "digest":
        receipt["progress"]["sourceDigest"] = "not-a-digest"
    elif fault == "summary":
        receipt["progress"]["summary"] = "x" * 32001
    else:
        receipt["progress"]["source"] = "terminal_capture"
    try:
        with pytest.raises(DomainError, match="INVALID_EXECUTOR_PROGRESS"):
            await CodingExecutor(store, Settings()).record(task, run, receipt)
        detail = await runtime.tasks.get("alice", task["id"])
        assert not detail["attempts"][0]["progress"]
        assert not detail["delivery"]["artifacts"]
    finally:
        await runtime.close()


async def test_running_task_without_a_bound_report_does_not_scan_its_workspace(store, tmp_path):
    runtime, task, run, receipt, _ = await reported_task(store, tmp_path)
    receipt.pop("progress")
    try:
        await CodingExecutor(store, Settings()).record(task, run, receipt)
        detail = await runtime.tasks.get("alice", task["id"])
        assert not detail["delivery"]["artifacts"]
        assert detail["attempts"][0]["result"] is None
    finally:
        await runtime.close()


async def test_final_report_retains_current_bytes_instead_of_accepting_an_older_provisional_copy(
    store, tmp_path
):
    from roami_agent.storage.database import now_ms

    runtime, task, run, receipt, page = await reported_task(store, tmp_path)
    try:
        await CodingExecutor(store, Settings()).record(task, run, receipt)
        provisional = (await runtime.tasks.get("alice", task["id"]))["delivery"]["artifacts"]
        old_html = next(a for a in provisional if a["name"] == "index.html")
        old_bytes = (await runtime.artifacts.read("alice", old_html["id"]))[1]
        current = "<!doctype html><title>Final report</title>"
        (page / "index.html").write_text(current)
        result = {"state": "succeeded", "summary": receipt["progress"]["summary"]}
        await store.call(
            lambda db: db.execute(
                "UPDATE task_attempts SET state='succeeded',result_json=?,finished_ms=? WHERE id=?",
                (json.dumps(result), now_ms(), run["id"]),
            ),
            write=True,
        )
        final = (await runtime.tasks.get("alice", task["id"]))["delivery"]["artifacts"]
        assert len(final) == 2 and all(not a["metadata"]["provisional"] for a in final)
        html = next(a for a in final if a["name"] == "index.html")
        assert html["id"] != old_html["id"]
        assert (await runtime.artifacts.read("alice", html["id"]))[1] == current.encode()
        assert (await runtime.artifacts.read("alice", old_html["id"]))[1] == old_bytes
    finally:
        await runtime.close()
