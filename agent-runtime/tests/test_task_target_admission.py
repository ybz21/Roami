"""Reject unavailable local destinations before accepting work or starting an executor."""

import json

import pytest
from test_routing_policy import setup
from test_task_delivery_benchmark import admit, mark

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row


async def test_resource_only_empty_optional_directory_is_not_a_workspace_request(store):
    runtime, _, _, _, binding = await setup(store)
    try:
        target = {"kind": "new_session", "resourceOnly": True, "directory": ""}
        first = await admit(runtime, binding, "查询济南天气，不写文件", "weather", target=target)
        replay = await admit(runtime, binding, "查询济南天气，不写文件", "weather", target=target)
        assert replay["id"] == first["id"]
        assert json.loads(first["intent_json"])["target"] == {
            "kind": "new_session",
            "resourceOnly": True,
        }
        assert target["directory"] == ""
    finally:
        await runtime.close()


@pytest.mark.parametrize("kind,key", [("new_session", "directory"), ("new_project", "baseDir")])
@pytest.mark.parametrize("path", ["missing", "relative", "file", "empty"])
async def test_invalid_local_path_never_creates_a_task(store, tmp_path, kind, key, path):
    runtime, _, _, tools, binding = await setup(store)
    source = tmp_path / "file.txt"
    source.write_text("not a directory")
    paths = {
        "missing": str(tmp_path / "missing"),
        "relative": "work",
        "file": str(source),
        "empty": "",
    }
    try:
        with pytest.raises(
            DomainError, match="^(INVALID_EXECUTION_DIRECTORY|EXECUTION_DIRECTORY_UNAVAILABLE)$"
        ):
            await tools.invoke(
                {
                    "function": {
                        "name": "delegate",
                        "arguments": json.dumps(
                            {
                                "goal": "Build report",
                                "target": {"kind": kind, "name": "report", key: paths[path]},
                            }
                        ),
                    }
                },
                "main",
                binding,
            )
        assert not await runtime.tasks.list("alice")
        assert not await store.call(lambda db: row(db, "SELECT id FROM jobs WHERE kind='task.run'"))
    finally:
        await runtime.close()


async def test_valid_path_admission_and_replay_after_directory_is_removed(store, tmp_path):
    runtime, _, _, _, binding = await setup(store)
    directory = tmp_path / "work"
    directory.mkdir()
    try:
        target = {"kind": "new_session", "directory": str(directory)}
        task = await admit(runtime, binding, "Build report", "one", target=target)
        directory.rmdir()
        assert (await admit(runtime, binding, "Build report", "one", target=target))["id"] == task[
            "id"
        ]
    finally:
        await runtime.close()


@pytest.mark.parametrize("executor", ["native", "codex", "claude"])
async def test_legacy_task_continuation_clears_old_step_and_time_limits(store, executor):
    runtime, _, _, _, binding = await setup(store)
    try:
        task = await admit(runtime, binding, "Build report", "one", executor=executor)
        await mark(runtime, task)
        await store.call(
            lambda db: db.execute(
                "UPDATE tasks SET budget_json=? WHERE id=?",
                (
                    json.dumps(
                        {
                            "deadlineMs": 1,
                            "maxTurns": 16,
                            "timeoutMs": 600000,
                            "usedSteps": 16,
                            "depth": 0,
                        }
                    ),
                    task["id"],
                ),
            ),
            write=True,
        )
        await runtime.tasks.revisions.request(
            "alice", task["id"], "Continue existing progress", 1, "continue"
        )
        await runtime.tasks.revisions.advance()
        updated = await store.call(
            lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],))
        )
        budget = json.loads(updated["budget_json"])
        assert updated["revision"] == 2
        assert {
            key: budget[key] for key in ["deadlineMs", "maxTurns", "timeoutMs", "usedSteps"]
        } == dict.fromkeys(["deadlineMs", "maxTurns", "timeoutMs", "usedSteps"], 0)
    finally:
        await runtime.close()


async def test_native_preparation_error_code_survives_cli_boundary(tmp_path):
    import sys
    from types import SimpleNamespace

    from roami_agent.executors.workspace import hold_workspace

    cli = tmp_path / "roami"
    cli.write_text(
        f"#!{sys.executable}\nimport json,sys\nsys.stdin.readline()\nprint(json.dumps({{'state':'failed','errorCode':'WORKSPACE_STALE'}}),flush=True)\nsys.exit(1)\n"
    )
    cli.chmod(0o700)
    settings = SimpleNamespace(cli_bin=str(cli), provider_key_environments=lambda: set())
    task = {
        "intent_json": json.dumps(
            {"target": {"kind": "project", "projectId": "p", "workspaceId": "w"}}
        ),
        "budget_json": "{}",
    }
    with pytest.raises(DomainError, match="^WORKSPACE_STALE$"):
        async with hold_workspace(settings, task, {"launch_id": "run"}):
            pytest.fail("Worker admitted without a workspace")
