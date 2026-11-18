from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from test_task_cancellation import QuietModel, task_run

from roami_agent.app import Runtime
from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.server.http import create_app


@pytest.mark.parametrize("cancelling", [None, "unknown", "stopping"])
@pytest.mark.parametrize(
    ("observation", "result", "expected_status", "expected_state"),
    [
        ({"state": "running", "session": "work"}, None, 200, "running"),
        (
            {
                "state": "succeeded",
                "result": {
                    "state": "succeeded",
                    "summary": "Known result",
                    "inputStopped": True,
                    "outcomeKnown": True,
                },
            },
            None,
            200,
            "waiting_user",
        ),
        ({"state": "unknown"}, "succeeded", 200, "waiting_user"),
        ({"state": "unknown"}, "failed", 200, "failed"),
        ({"state": "unknown"}, "cancelled", 200, "cancelled"),
        ({"state": "unknown"}, "unconfirmed", 409, "running"),
        ({"state": "unknown"}, OSError("offline"), 409, "running"),
        (TimeoutError(), None, 409, "running"),
    ],
)
async def test_reconcile_without_a_report_never_accepts_or_relaunches_work(
    store, cancelling, observation, result, expected_status, expected_state
):
    executor = CodingExecutor(store, SimpleNamespace())
    terminal = (
        {
            "result": {
                "state": "succeeded" if result == "unconfirmed" else result,
                "summary": "Recovered result",
                "inputStopped": result != "unconfirmed",
                "outcomeKnown": result != "unconfirmed",
            }
        }
        if isinstance(result, str)
        else result
    )
    executor.command = AsyncMock(side_effect=[observation, terminal])
    runtime = Runtime(
        store, QuietModel(), executor=executor, verifier=AsyncMock(return_value=False)
    )
    try:
        conversation = await runtime.conversations.create("alice")
        task, run = await task_run(runtime, conversation, "reconcile-no-report")
        if cancelling:
            await runtime.tasks.cancel("alice", task["id"])
        await store.call(
            lambda db: db.execute(
                "UPDATE task_attempts SET executor_kind='cli',state=? WHERE id=?",
                (cancelling or "unknown", run["id"]),
            ),
            write=True,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
            base_url="http://agent",
            headers={"X-Roami-Owner": "alice"},
        ) as client:
            response = await client.post(
                f"/v1/tasks/{task['id']}/reconcile", json={"revision": 1, "runId": run["id"]}
            )
        assert response.status_code == expected_status
        settled_state = (
            ("cancelling" if expected_state == "running" else "cancelled")
            if cancelling
            else expected_state
        )
        if expected_status == 409:
            assert response.json()["error"]["code"] == "TASK_STOP_UNCONFIRMED"
        else:
            assert response.json()["data"]["state"] == settled_state
        detail = await runtime.tasks.get("alice", task["id"])
        assert detail["task"]["state"] == settled_state
        if expected_state == "running":
            assert detail["attempts"][0]["result"] is None
            assert detail["attempts"][0]["state"] == (
                "running"
                if observation == {"state": "running", "session": "work"}
                else cancelling or "unknown"
                if isinstance(observation, Exception)
                else "unknown"
            )
        commands = [call.args for call in executor.command.call_args_list]
        assert commands[0] == ("status", "--key", run["launch_id"])
        assert commands[1:] == (
            [("reconcile-session", "--key", run["launch_id"])] if result is not None else []
        )
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    ("owner", "body", "status", "code"),
    [
        ("bob", {"revision": 1, "runId": "current"}, 404, "TASK_NOT_FOUND"),
        ("alice", {"revision": 2, "runId": "current"}, 409, "TASK_REVISION_CHANGED"),
        ("alice", {"revision": 1, "runId": "stale"}, 409, "TASK_RESULT_SUPERSEDED"),
        ("alice", {"runId": "current"}, 422, "INVALID_REQUEST"),
        ("alice", {"revision": 1}, 422, "INVALID_REQUEST"),
        ("alice", {"revision": 1, "runId": "current", "accepted": True}, 422, "INVALID_REQUEST"),
    ],
)
async def test_reconciliation_rejects_missing_or_stale_identity_before_executor_access(
    store, owner, body, status, code
):
    executor = SimpleNamespace(can_reconcile=True, command=AsyncMock())
    runtime = Runtime(store, QuietModel(), executor=executor)
    try:
        conversation = await runtime.conversations.create("alice")
        task, run = await task_run(runtime, conversation, "reconcile-identity")
        if body.get("runId") == "current":
            body = {**body, "runId": run["id"]}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime, manage_lifecycle=False)),
            base_url="http://agent",
            headers={"X-Roami-Owner": owner},
        ) as client:
            response = await client.post(f"/v1/tasks/{task['id']}/reconcile", json=body)
        assert response.status_code == status
        assert response.json()["error"]["code"] == code
        executor.command.assert_not_called()
    finally:
        await runtime.close()
