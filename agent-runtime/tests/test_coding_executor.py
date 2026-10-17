"""Unknown process outcomes must never be converted into successful cancellation or replay."""

from roami_agent.coding_executor import CodingExecutor
from roami_agent.configuration import Settings
from roami_agent.conversation import Conversations
from roami_agent.storage import row
from roami_agent.tasks import Tasks


def test_go_launcher_is_used_even_without_agent_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("ROAMI_AGENT_CLI", "/selected/roami")
    assert Settings.load(tmp_path / "missing.toml").cli_bin == "/selected/roami"


async def test_monitor_waits_for_launch_and_preserves_unknown_outcome(store):
    conversations = Conversations(store)
    tasks = Tasks(store, conversations)
    conversation = await conversations.create("alice")
    task = await tasks.create(
        "alice",
        conversation["id"],
        "work",
        key="external-race",
        executor="codex",
        record_intent=True,
    )
    executor = CodingExecutor(store, Settings())
    calls = []
    receipt = {"state": "unknown"}

    async def command(*args, **kwargs):
        calls.append(args)
        return receipt

    executor.command = command

    def launching(db):
        db.execute("UPDATE tasks SET state='running' WHERE id=?", (task["id"],))
        db.execute("UPDATE task_attempts SET state='running' WHERE task_id=?", (task["id"],))
        db.execute("UPDATE jobs SET state='running' WHERE aggregate_id=?", (task["id"],))

    await store.call(launching, write=True)
    await executor.poll(tasks)
    assert not calls  # Missing evidence while launch is in progress proves nothing.
    await store.call(
        lambda db: db.execute("UPDATE jobs SET state='done' WHERE aggregate_id=?", (task["id"],)),
        write=True,
    )
    await executor.poll(tasks)
    await executor.poll(tasks)
    current = (await tasks.list("alice"))[0]
    assert current["state"] == "running"
    assert current["latestAttempt"]["state"] == "unknown"
    events = await conversations.events("alice", conversation["id"])
    assert sum(e["kind"] == "task.observation_unknown" for e in events) == 1
    assert all(call[0] == "status" for call in calls)
    await tasks.cancel("alice", task["id"])
    await executor.poll(tasks)
    assert (await tasks.list("alice"))[0]["state"] == "cancelling"
    receipt = {"state": "cancelled", "result": {"state": "cancelled", "summary": "Stopped"}}
    await executor.poll(tasks)
    assert (await tasks.list("alice"))[0]["state"] == "cancelled"
    attempt = await store.call(
        lambda db: row(db, "SELECT result_json FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    assert attempt["result_json"]


async def test_project_execution_passes_identity_and_persists_go_preparation(store, tmp_path):
    import json

    import pytest

    from roami_agent.storage import DomainError

    conversations = Conversations(store)
    tasks = Tasks(store, conversations)
    conversation = await conversations.create("alice")
    task = await tasks.create(
        "alice",
        conversation["id"],
        "Update project",
        key="project",
        executor="codex",
        target={"kind": "project", "projectId": "stable-project"},
        record_intent=True,
    )
    run = await store.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='preparing' WHERE id=?", (task["id"],)),
        write=True,
    )
    executor = CodingExecutor(store, Settings(coding_directory=tmp_path / "unrelated-directory"))
    workspace = {
        "projectId": "stable-project",
        "directory": str(tmp_path / "prepared"),
        "branch": "agent/task",
        "startOid": "a" * 40,
        "base": "main",
    }
    receipt = {"state": "running", "session": "stable-session", "workspace": workspace}
    calls = []

    async def command(sub, *args, spec=None):
        calls.append(spec)
        return receipt

    executor.command = command
    assert await executor.run(task, run) is None
    assert calls[0]["projectId"] == "stable-project"
    assert "directory" not in calls[0]
    current = (await tasks.list("alice"))[0]
    assert current["state"] == "running"
    assert current["latestAttempt"]["workspace"] == workspace
    assert json.loads(current["target_json"])["sessionId"] == "stable-session"
    await executor.record(task, run, receipt)
    events = await conversations.events("alice", conversation["id"])
    assert sum(e["kind"] == "task.workspace_prepared" for e in events) == 1
    assert sum(e["kind"] == "task.started" for e in events) == 1
    with pytest.raises(DomainError, match="WORKSPACE_BINDING_CONFLICT"):
        await executor.record(
            task, run, {**receipt, "workspace": {**workspace, "projectId": "other-project"}}
        )
    assert (await tasks.list("alice"))[0]["latestAttempt"]["workspace"] == workspace
