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


@pytest.mark.parametrize("provider", ["claude", "codex", "opencode"])
@pytest.mark.parametrize("persistent", [True, False])
@pytest.mark.parametrize("target_kind", ["new_session", "project"])
async def test_new_delegated_tasks_launch_in_auto_mode(
    store, tmp_path, provider, persistent, target_kind
):
    conversations = Conversations(store)
    tasks = Tasks(store, conversations)
    conversation = await conversations.create("alice")
    target = {"kind": target_kind}
    if target_kind == "project":
        target["projectId"] = "existing-project"
    else:
        target["directory"] = str(tmp_path)
    task = await tasks.create(
        "alice",
        conversation["id"],
        "Update the project",
        key="auto-mode",
        executor=provider,
        target=target,
        record_intent=True,
    )
    run = await store.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    executor = CodingExecutor(store, Settings(), persistent=persistent)
    launches = []

    async def command(sub, *args, spec=None):
        assert sub == "launch"
        launches.append(spec)
        return {"state": "unknown"}

    executor.command = command
    assert await executor.run(task, run) is None
    assert len(launches) == 1
    assert launches[0]["executor"] == provider
    assert launches[0]["persistent"] is persistent
    assert launches[0]["permission"] == "auto"


@pytest.mark.parametrize("provider", ["codex", "claude", "opencode", "pi"])
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
        assert "permission" not in spec
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


@pytest.mark.parametrize("executor", ["native", "codex", "claude", "opencode", "pi"])
async def test_loose_task_rejects_project_parent_directory_before_recording_intent(store, executor):
    from roami_agent.protocol.errors import DomainError

    conversations = Conversations(store)
    tasks = Tasks(store, conversations)
    conversation = await conversations.create("alice")
    with pytest.raises(DomainError, match="LOOSE_SESSION_USE_DIRECTORY"):
        await tasks.create(
            "alice",
            conversation["id"],
            "work",
            key="bad-directory",
            executor=executor,
            target={"kind": "new_session", "baseDir": "/requested/work"},
            record_intent=True,
        )
    assert await store.call(lambda db: db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]) == 0
    assert (
        await store.call(lambda db: db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]) == 0
    )


@pytest.mark.parametrize("executor", ["native", "codex"])
async def test_restored_loose_task_does_not_fall_back_when_directory_field_is_wrong(
    store, executor
):
    import json

    from roami_agent.executors.workspace import hold_workspace
    from roami_agent.protocol.errors import DomainError

    task = {
        "intent_json": json.dumps({"target": {"kind": "new_session", "baseDir": "/requested/work"}})
    }
    settings = Settings(cli_bin="/must-not-launch", coding_directory="/wrong-default")
    with pytest.raises(DomainError, match="LOOSE_SESSION_USE_DIRECTORY"):
        if executor == "native":
            async with hold_workspace(settings, task, {}):
                pytest.fail("Invalid task reached the workspace")
        else:
            await CodingExecutor(store, settings).run(task, {})


async def test_observation_recovery_updates_feed_and_later_uncertainty_without_relaunch(store):
    conversations = Conversations(store)
    tasks = Tasks(store, conversations)
    conversation = await conversations.create("alice")
    task = await tasks.create(
        "alice",
        conversation["id"],
        "work",
        key="observation-recovery",
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

    def launched(db):
        db.execute("UPDATE tasks SET state='running' WHERE id=?", (task["id"],))
        db.execute("UPDATE task_attempts SET state='running' WHERE task_id=?", (task["id"],))
        db.execute("UPDATE jobs SET state='done' WHERE aggregate_id=?", (task["id"],))

    await store.call(launched, write=True)
    await executor.poll(tasks)
    receipt = {"state": "running", "session": "observed-session"}
    await executor.poll(tasks)
    await executor.poll(tasks)
    events = await conversations.events("alice", conversation["id"])
    resumed = [e for e in events if e["kind"] == "task.observation_recovered"]
    assert len(resumed) == 1
    assert resumed[0]["payload"]["activity"]["state"] == "running"
    assert not resumed[0]["payload"]["activity"]["errorCode"]
    assert (await tasks.list("alice"))[0]["latestAttempt"]["state"] == "running"
    receipt = {"state": "unknown"}
    await executor.poll(tasks)
    await executor.poll(tasks)
    events = await conversations.events("alice", conversation["id"])
    unknown = [e for e in events if e["kind"] == "task.observation_unknown"]
    assert len(unknown) == 2 and unknown[-1]["id"] > resumed[0]["id"]
    assert unknown[-1]["payload"]["activity"]["state"] == "unknown"
    assert all(call[0] == "status" for call in calls)
    assert (await tasks.list("alice"))[0]["state"] == "running"


async def test_unknown_preparing_execution_is_visible_without_ending_task(store):
    conversations = Conversations(store)
    tasks = Tasks(store, conversations)
    conversation = await conversations.create("alice")
    task = await tasks.create(
        "alice",
        conversation["id"],
        "work",
        key="preparing-observation",
        executor="codex",
        record_intent=True,
    )
    await store.call(
        lambda db: db.execute("UPDATE tasks SET state='preparing' WHERE id=?", (task["id"],)),
        write=True,
    )
    run = await store.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    executor = CodingExecutor(store, Settings())
    await executor.record(task, run, {"state": "unknown"})
    await executor.record(task, run, {"state": "unknown"})
    events = await conversations.events("alice", conversation["id"])
    unknown = [e for e in events if e["kind"] == "task.observation_unknown"]
    assert len(unknown) == 1
    assert unknown[0]["payload"]["activity"]["state"] == "unknown"
    assert (await tasks.list("alice"))[0]["state"] == "preparing"
