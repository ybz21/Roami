"""Unknown process outcomes must never be converted into successful cancellation or replay."""

import pytest

from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.tasks import Tasks
from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


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
    assert (await tasks.list("alice"))[0]["state"] == "cancelling"
    from roami_agent.dispatch.runner import TaskDispatcher

    verification = await store.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE aggregate_id=? AND kind='task.verify'", (task["id"],)
        )
    )
    await TaskDispatcher(store, tasks, executor, None, None, None, {}).verify(verification)
    assert (await tasks.list("alice"))[0]["state"] == "cancelled"
    attempt = await store.call(
        lambda db: row(db, "SELECT result_json FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    assert attempt["result_json"]


async def test_project_execution_passes_identity_and_persists_go_preparation(store, tmp_path):
    import json

    import pytest

    from roami_agent.protocol.errors import DomainError

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


async def test_explicit_workspace_reuse_passes_stable_identity_without_directory_override(store):
    import json

    import pytest

    from roami_agent.protocol.errors import DomainError

    conversations = Conversations(store)
    tasks = Tasks(store, conversations)
    c = await conversations.create("alice")
    task = await tasks.create(
        "alice",
        c["id"],
        "Continue the existing branch",
        key="reuse",
        executor="codex",
        target={"kind": "project", "projectId": "project", "workspaceId": "workspace"},
        record_intent=True,
    )
    run = await store.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    executor = CodingExecutor(store, Settings())
    captured = []

    async def command(sub, *args, spec=None):
        captured.append(spec)
        return {
            "state": "running",
            "session": "continued-session",
            "workspace": {
                "workspaceId": "workspace",
                "projectId": "project",
                "directory": "/prepared/branch",
            },
        }

    executor.command = command
    assert await executor.run(task, run) is None
    assert captured[0]["workspaceId"] == "workspace" and "directory" not in captured[0]
    current = (await tasks.list("alice"))[0]
    assert json.loads(current["target_json"])["workspaceId"] == "workspace"
    spec = json.loads(task["intent_json"])
    spec["target"]["base"] = "main"
    with pytest.raises(DomainError, match="CODING_WORKSPACE_REUSE_CONFLICT"):
        await executor.run(dict(task, intent_json=json.dumps(spec)), run)
    assert len(captured) == 1


async def test_coding_new_project_resolves_before_launch_without_using_loose_directory(
    store, tmp_path, monkeypatch
):
    from roami_agent.executors import roami_cli

    conversations = Conversations(store)
    tasks = Tasks(store, conversations)
    c = await conversations.create("alice")
    task = await tasks.create(
        "alice",
        c["id"],
        "Create expense tracker",
        key="new-project",
        executor="claude",
        target={"kind": "new_project", "name": "Expense Tracker"},
        record_intent=True,
    )
    run = await store.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    calls = []

    async def provision(settings, original, attempt):
        calls.append("provision")
        assert original["id"] == task["id"] and attempt["id"] == run["id"]
        return {"kind": "project", "projectId": "new-stable-id"}

    monkeypatch.setattr(roami_cli, "provision_project", provision)
    executor = CodingExecutor(store, Settings(coding_directory=tmp_path))

    async def command(sub, *args, spec=None):
        calls.append("launch")
        assert spec["projectId"] == "new-stable-id" and "directory" not in spec
        return {
            "state": "running",
            "session": "new-project-session",
            "workspace": {
                "projectId": "new-stable-id",
                "workspaceId": "prepared-id",
                "directory": str(tmp_path / "new-project"),
            },
        }

    executor.command = command
    assert await executor.run(task, run) is None
    assert calls == ["provision", "launch"]


@pytest.mark.parametrize("provider", ["codex", "claude"])
async def test_session_continuation_keeps_provider_identity_and_rejects_rebinding(
    store, tmp_path, provider
):
    import pytest

    from roami_agent.protocol.errors import DomainError

    conversations = Conversations(store)
    tasks = Tasks(store, conversations)
    c = await conversations.create("alice")
    task = await tasks.create(
        "alice",
        c["id"],
        "Continue",
        key="session",
        executor=provider,
        target={"kind": "session", "sessionId": "stable-session", "projectId": "context-only"},
        record_intent=True,
    )
    run = await store.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    executor = CodingExecutor(store, Settings(coding_directory=tmp_path / "unrelated"))
    receipt = {
        "state": "running",
        "session": "stable-session",
        "sessionBinding": {"id": "stable-session", "providerConversationId": "exact-provider-id"},
        "workspace": {"directory": str(tmp_path)},
    }

    async def command(sub, *args, spec=None):
        assert spec["executor"] == provider
        assert spec["sessionId"] == "stable-session"
        assert "directory" not in spec and "projectId" not in spec
        return receipt

    executor.command = command
    assert await executor.run(task, run) is None
    assert (await tasks.list("alice"))[0]["latestAttempt"][
        "agentConversationId"
    ] == "exact-provider-id"
    with pytest.raises(DomainError, match="SESSION_BINDING_CONFLICT"):
        await executor.record(
            task,
            run,
            {
                **receipt,
                "sessionBinding": {
                    "id": "stable-session",
                    "providerConversationId": "wrong-provider",
                },
            },
        )
    assert (await tasks.list("alice"))[0]["latestAttempt"][
        "agentConversationId"
    ] == "exact-provider-id"


async def test_session_preflight_rejection_is_distinct_from_submission_uncertainty(store):
    from roami_agent.protocol.errors import DomainError

    conversations = Conversations(store)
    tasks = Tasks(store, conversations)
    c = await conversations.create("alice")
    task = await tasks.create(
        "alice",
        c["id"],
        "Continue",
        key="preflight",
        executor="codex",
        target={"kind": "session", "sessionId": "stable-session"},
        record_intent=True,
    )
    run = await store.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    executor = CodingExecutor(store, Settings())
    code = "SESSION_LIFECYCLE_UNAVAILABLE"

    async def command(*args, **kwargs):
        raise DomainError(code)

    executor.command = command
    assert await executor.run(task, run) == {"state": "failed", "summary": code}
    code = "SESSION_SUBMISSION_UNKNOWN"
    assert await executor.run(task, run) is None
    assert (await tasks.list("alice"))[0]["latestAttempt"]["state"] == "unknown"
