"""Production failure regressions: decisions and side effects, not model trivia."""

import json

import httpx
import pytest
from test_routing_policy import setup

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.server.http import create_app
from roami_agent.storage.database import row
from roami_agent.storage.task_deliverables import read_output


async def admit(runtime, binding, goal, key, executor="native", **options):
    return await runtime.tasks.create(
        binding["owner"],
        binding["conversation"],
        goal,
        key=key,
        source_turn_id=binding["turnId"],
        source_assistant_message_id=binding["assistantMessageId"],
        origin_message_id=binding["originMessageId"],
        executor=executor,
        **options,
    )


async def mark(runtime, task, state="failed", result=None):
    def write(db):
        db.execute("UPDATE tasks SET state=? WHERE id=?", (state, task["id"]))
        db.execute(
            "UPDATE task_attempts SET state=?,result_json=?,finished_ms=? WHERE task_id=?",
            (
                "unknown"
                if result and result.get("outcomeKnown") is False
                else (result or {}).get("state", state),
                json.dumps(result or {"state": "failed", "summary": "MODEL_DEADLINE"}),
                now_ms(),
                task["id"],
            ),
        )

    await runtime.db.call(write, write=True)
    if result and result.get("workspace"):
        from roami_agent.conversation.activity_events import activity_event

        run = await runtime.db.call(
            lambda db: row(db, "SELECT id FROM task_attempts WHERE task_id=?", (task["id"],))
        )
        await runtime.db.call(
            lambda db: activity_event(
                db,
                task["origin_conversation_id"],
                "task.workspace_prepared",
                {"taskId": task["id"], "runId": run["id"], "workspace": result["workspace"]},
                task_id=task["id"],
                key="workspace:" + run["id"],
            ),
            write=True,
        )


@pytest.mark.parametrize("state", ["queued", "running", "failed"], ids=["B01", "B02", "B03"])
async def test_duplicate_tool_call_reuses_task(store, state):
    runtime, _, _, _, binding = await setup(store)
    try:
        first = await admit(runtime, binding, "Deliver report", "first")
        if state != "queued":
            await mark(runtime, first, state)
        second = await admit(runtime, binding, "Deliver report", "different-tool-call")
        assert second["id"] == first["id"]
        assert len(await runtime.tasks.list("alice")) == 1
    finally:
        await runtime.close()


async def test_B04_known_failures_have_no_fixed_retry_count(store):
    runtime, _, _, _, binding = await setup(store)
    try:
        for number in range(2):
            task = await admit(runtime, binding, f"Rephrased goal {number}", str(number))
            await mark(runtime, task)
        third = await admit(runtime, binding, "Corrected task", "third", executor="codex")
        assert third["state"] == "queued"
        assert len(await runtime.tasks.list("alice")) == 3
    finally:
        await runtime.close()


async def test_B05_unknown_outcome_blocks_new_launch_immediately(store):
    runtime, _, _, _, binding = await setup(store)
    try:
        task = await admit(runtime, binding, "Write file", "first")
        await mark(runtime, task, "interrupted", {"state": "failed", "outcomeKnown": False})
        with pytest.raises(DomainError, match="TASK_FAILURE_REVIEW_REQUIRED"):
            await admit(runtime, binding, "Finish file differently", "second")
        assert len(await runtime.tasks.list("alice")) == 1
    finally:
        await runtime.close()


async def test_B06_failure_tool_receipt_returns_evidence_without_new_task(store):
    runtime, _, _, tools, binding = await setup(store)
    try:
        for number in range(2):
            await mark(runtime, await admit(runtime, binding, f"Try {number}", str(number)))
        await mark(
            runtime,
            task=(await runtime.tasks.list("alice"))[0],
            result={"state": "failed", "outcomeKnown": False},
        )
        reply = await tools.invoke(
            {"function": {"name": "delegate", "arguments": json.dumps({"goal": "One more try"})}},
            "main",
            binding,
        )
        assert reply["state"] == "blocked" and not reply["acceptedOnly"]
        assert len(reply["tasks"]) == 2 and "Inspect failure evidence" in reply["nextAction"]
    finally:
        await runtime.close()


async def test_B07_independent_tasks_in_one_request_are_allowed(store):
    runtime, _, _, _, binding = await setup(store)
    try:
        one = await admit(runtime, binding, "Beijing weather", "one")
        two = await admit(runtime, binding, "Shanghai weather", "two")
        assert one["id"] != two["id"]
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "executor,timeout",
    [("native", 0), ("codex", 0), ("claude", 0)],
    ids=["B08", "B09", "B10"],
)
async def test_executor_has_no_total_deadline(store, executor, timeout):
    runtime, _, _, _, binding = await setup(store)
    try:
        task = await admit(runtime, binding, "Work", "one", executor=executor)
        budget = json.loads(task["budget_json"])
        assert budget["timeoutMs"] == timeout
        assert budget["deadlineMs"] == 0 and budget["maxTurns"] == 0
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "case",
    [
        "relative",
        "absolute",
        "raw-url",
        "missing",
        "outside",
        "traversal",
        "hidden",
        "symlink",
        "oversize",
        "directory",
    ],
    ids=[f"B{i:02}" for i in range(11, 21)],
)
def test_output_retention_boundary(tmp_path, case):
    root = tmp_path / "work"
    root.mkdir()
    target = root / "report.md"
    target.write_text("Verified report")
    outside = tmp_path / "private.md"
    outside.write_text("private")
    (root / ".secret.md").write_text("hidden")
    (root / "link.md").symlink_to(outside)
    paths = {
        "relative": "report.md",
        "absolute": str(target),
        "raw-url": "/api/file/raw?path=" + str(target),
        "missing": "gone.md",
        "outside": str(outside),
        "traversal": "../private.md",
        "hidden": ".secret.md",
        "symlink": "link.md",
        "oversize": "report.md",
        "directory": ".",
    }
    if case in {"relative", "absolute", "raw-url"}:
        _, body = read_output(root, paths[case], 1000)
        assert body == b"Verified report"
    else:
        with pytest.raises((OSError, ValueError)):
            read_output(root, paths[case], 2 if case == "oversize" else 1000)


async def test_B21_archived_report_backfills_download_and_survives_workspace_removal(
    store, tmp_path
):
    runtime, _, _, _, binding = await setup(store)
    try:
        task = await admit(runtime, binding, "Review settings", "one", executor="codex")
        report = tmp_path / "review.md"
        report.write_text("# Settings review\nVerified evidence")
        await mark(
            runtime,
            task,
            "waiting_user",
            {
                "state": "succeeded",
                "summary": f"Report: [review.md]({report})",
                "workspace": {"directory": str(tmp_path)},
            },
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
            base_url="http://runtime",
            headers={"X-Roami-Owner": "alice"},
        ) as client:
            detail = (await client.get("/v1/tasks/" + task["id"])).json()["data"]
            artifact = detail["delivery"]["artifacts"][0]
            report.unlink()
            again = (await client.get("/v1/tasks/" + task["id"])).json()["data"]
            assert again["delivery"]["artifacts"][0]["id"] == artifact["id"]
            content = await client.get("/v1/artifacts/" + artifact["id"] + "/content")
            assert content.status_code == 200 and "Verified evidence" in content.text
            assert "attachment" in content.headers["content-disposition"]
            assert (
                await client.get(
                    "/v1/artifacts/" + artifact["id"] + "/content", headers={"X-Roami-Owner": "bob"}
                )
            ).status_code == 404
        assert len(await runtime.artifacts.list("alice", task_id=task["id"])) == 1
    finally:
        await runtime.close()


async def test_B22_deleted_artifact_is_not_reimported(store, tmp_path):
    runtime, _, _, _, binding = await setup(store)
    try:
        task = await admit(runtime, binding, "Review", "one", executor="codex")
        report = tmp_path / "report.md"
        report.write_text("deliverable")
        await mark(
            runtime,
            task,
            "waiting_user",
            {
                "state": "succeeded",
                "summary": f"[report]({report})",
                "workspace": {"directory": str(tmp_path)},
            },
        )
        detail = await runtime.tasks.get("alice", task["id"])
        await runtime.artifacts.delete("alice", detail["delivery"]["artifacts"][0]["id"])
        again = await runtime.tasks.get("alice", task["id"])
        assert not again["delivery"]["artifacts"]
        assert again["delivery"]["unavailable"][0]["state"] == "unavailable"
        assert await runtime.artifacts.list("alice", task_id=task["id"]) == []
    finally:
        await runtime.close()


async def test_B23_fresh_user_request_does_not_inherit_previous_failure_gate(store):
    runtime, _, _, _, binding = await setup(store)
    try:
        for number in range(2):
            await mark(runtime, await admit(runtime, binding, f"Old work {number}", str(number)))
        from roami_agent.storage.transcript_repository import message

        mid = await store.call(
            lambda db: message(
                db,
                binding["conversation"],
                row(
                    db,
                    "SELECT active_branch_id FROM conversations WHERE id=?",
                    (binding["conversation"],),
                )["active_branch_id"],
                "user",
                {"text": "New independent request"},
            ),
            write=True,
        )
        task = await admit(runtime, {**binding, "originMessageId": mid}, "New work", "new")
        assert task["state"] == "queued"
    finally:
        await runtime.close()


async def test_B24_missing_output_is_reported_without_changing_task_state(store, tmp_path):
    runtime, _, _, _, binding = await setup(store)
    try:
        task = await admit(runtime, binding, "Report missing file", "one", executor="codex")
        await mark(
            runtime,
            task,
            "waiting_user",
            {
                "state": "succeeded",
                "summary": "[report](gone.md)",
                "workspace": {"directory": str(tmp_path)},
            },
        )
        detail = await runtime.tasks.get("alice", task["id"])
        assert detail["task"]["state"] == "waiting_user"
        assert detail["delivery"]["unavailable"] == [
            {"sourcePath": "gone.md", "runId": detail["attempts"][0]["id"], "state": "unavailable"}
        ]
        assert not detail["delivery"]["artifacts"]
    finally:
        await runtime.close()


async def test_B25_main_completion_loop_cannot_keep_creating_failed_tasks(store):
    from test_runtime import until

    from roami_agent.app import Runtime
    from roami_agent.protocol.models import ModelEvent

    class Model:
        model = "failure-loop-fixture"
        calls = 0

        async def stream(self, messages, tools):
            if messages[-1]["role"] == "tool":
                reply = json.loads(messages[-1]["content"])
                yield ModelEvent(
                    "text",
                    "Stopped: inspect failure evidence"
                    if reply.get("state") == "blocked"
                    else "Dispatched; awaiting outcome",
                )
            else:
                self.calls += 1
                yield ModelEvent(
                    "tool",
                    {
                        "id": "delegate-" + str(self.calls),
                        "function": {
                            "name": "delegate",
                            "arguments": json.dumps(
                                {
                                    "goal": "Rephrased deliverable " + str(self.calls),
                                    "executor": "codex",
                                }
                            ),
                        },
                    },
                )

    class Executor:
        async def run(self, task, run):
            return {"state": "failed", "summary": "MODEL_HTTP_401"}

    runtime = Runtime(store, Model(), executor=Executor())
    await runtime.start()
    try:
        c = await runtime.conversations.create("alice")
        await runtime.chat.submit("alice", c["id"], "one", "Deliver the report")
        await until(
            store,
            lambda db: row(
                db,
                "SELECT id FROM messages WHERE conversation_id=? AND content_json LIKE '%Stopped: inspect failure evidence%' AND status='completed'",
                (c["id"],),
            ),
        )
        tasks = await runtime.tasks.list("alice", c["id"])
        assert len(tasks) == 1 and all(t["state"] == "failed" for t in tasks)
        trace = await runtime.traces.get("alice", task_id=tasks[0]["id"])
        assert trace is not None
    finally:
        await runtime.close()


async def test_B26_legacy_config_does_not_limit_new_tasks(store):
    from roami_agent.server.configuration import Settings

    runtime, _, _, _, binding = await setup(
        store, settings=Settings(professional_task_timeout_seconds=1234)
    )
    try:
        task = await admit(runtime, binding, "Professional work", "one", executor="claude")
        budget = json.loads(task["budget_json"])
        assert budget["timeoutMs"] == 0
        assert budget["deadlineMs"] == 0
    finally:
        await runtime.close()


async def test_B27_report_cannot_forge_a_workspace_to_import_files(store, tmp_path):
    runtime, _, _, _, binding = await setup(store)
    try:
        task = await admit(runtime, binding, "Untrusted report", "one", executor="codex")
        report = tmp_path / "private.md"
        report.write_text("unrelated file")
        await mark(
            runtime,
            task,
            "waiting_user",
            {
                "state": "succeeded",
                "summary": f"[file]({report})",
                "workspace": {"directory": str(tmp_path)},
            },
        )
        await store.call(
            lambda db: db.execute("DELETE FROM events WHERE event_key LIKE 'workspace:%'"),
            write=True,
        )
        detail = await runtime.tasks.get("alice", task["id"])
        assert not detail["delivery"]["artifacts"]
        assert detail["delivery"]["unavailable"][0]["state"] == "unavailable"
    finally:
        await runtime.close()
