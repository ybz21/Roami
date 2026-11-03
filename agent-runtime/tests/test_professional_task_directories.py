"""A stale loose-task workspace must not block unrelated professional tasks."""

import json
from pathlib import Path

import pytest
from test_routing_policy import request, setup

from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.tasks import Tasks
from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


@pytest.mark.parametrize("provider", ["claude", "codex", "opencode", "pi"])
@pytest.mark.parametrize("configured", [False, True])
async def test_implicit_professional_directories_are_private_and_stable(
    store, tmp_path, provider, configured
):
    shared = tmp_path / "agent-coding"
    shared.mkdir()
    (shared / "existing.txt").write_text("preserve the previous writer")
    settings = Settings(coding_directory=shared if configured else None)
    conversations = Conversations(store)
    tasks = Tasks(store, conversations)
    conversation = await conversations.create("alice")
    executor = CodingExecutor(store, settings)
    launches = []

    async def command(sub, *args, spec=None):
        assert sub == "launch"
        launches.append(spec)
        directory = Path(spec["directory"])
        assert directory.is_dir() and directory != shared
        return {"state": "unknown"}

    executor.command = command
    directories = []
    for key in ("first", "second"):
        task = await tasks.create(
            "alice",
            conversation["id"],
            "Write a report",
            key=key,
            executor=provider,
            record_intent=True,
        )
        run = await store.call(
            lambda db, task_id=task["id"]: row(
                db, "SELECT * FROM task_attempts WHERE task_id=?", (task_id,)
            )
        )
        await executor.run(task, run)
        directory = Path(launches[-1]["directory"])
        directories.append(directory)
        assert directory.name == task["id"]
        assert directory.is_relative_to(store.data_root / "agents" / "task-directories")
        (directory / "draft.txt").write_text(key)
        await executor.run(task, run)
        assert Path(launches[-1]["directory"]) == directory
        assert (directory / "draft.txt").read_text() == key
        assert json.loads(task["intent_json"])["target"] == {"kind": "new_session"}
    assert directories[0] != directories[1]
    assert (shared / "existing.txt").read_text() == "preserve the previous writer"


async def test_professional_directory_preparation_failure_never_launches_cli(store, monkeypatch):
    conversations = Conversations(store)
    tasks = Tasks(store, conversations)
    conversation = await conversations.create("alice")
    task = await tasks.create(
        "alice", conversation["id"], "Report", key="denied", executor="claude", record_intent=True
    )
    run = await store.call(
        lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],))
    )
    executor = CodingExecutor(store, Settings())

    async def denied(*args):
        raise DomainError("TASK_DIRECTORY_UNAVAILABLE")

    async def forbidden(*args, **kwargs):
        pytest.fail("CLI launched after directory preparation failed")

    monkeypatch.setattr("roami_agent.executors.roami_cli.prepare_task_directory", denied)
    executor.command = forbidden
    with pytest.raises(DomainError, match="TASK_DIRECTORY_UNAVAILABLE"):
        await executor.run(task, run)


async def test_professional_routing_does_not_require_a_shared_default_directory(store):
    runtime, _, router, _, binding = await setup(store, settings=Settings())
    try:
        decision = await router.decide(request(), binding)
        assert decision["executor"] in {"claude", "codex"}
        assert decision["targetRef"] == {"kind": "new_session"}
    finally:
        await runtime.close()
