"""Unscoped native file tasks have real writable, task-owned directories."""

import json
from pathlib import Path

import pytest
from native_prompt_messages import dialogue_messages
from test_runtime import ConversationModel, until
from test_task_delivery_benchmark import mark

from roami_agent.app import Runtime
from roami_agent.executors.task_directory import prepare_task_directory
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import row


@pytest.mark.parametrize("configured", [False, True])
async def test_native_creates_and_delivers_a_file_without_a_directory_or_go_workspace(
    store, tmp_path, configured
):
    selected = []

    class Worker:
        model = "native-file-fixture"

        async def stream(self, messages, tools):
            messages = dialogue_messages(messages)
            workspace = json.JSONDecoder().raw_decode(
                messages[0]["content"].split(
                    "Prepared task workspace (trusted runtime binding): ", 1
                )[1]
            )[0]
            selected.append(workspace["directory"])
            count = sum(m["role"] == "tool" for m in messages)
            if count == 0:
                name, args = (
                    "write",
                    {"path": "report.md", "expectedSha256": None, "content": "任务目录可写"},
                )
            elif count == 1:
                name, args = "read", {"path": "report.md"}
            else:
                assert "任务目录可写" in messages[-1]["content"]
                yield ModelEvent("text", "已写入并回读 report.md")
                return
            yield ModelEvent(
                "tool",
                {"id": str(count), "function": {"name": name, "arguments": json.dumps(args)}},
            )

    runtime = Runtime(
        store,
        ConversationModel(),
        worker_model=Worker(),
        settings=Settings(coding_directory=tmp_path if configured else None),
    )

    def forbidden(*args, **kwargs):
        pytest.fail("An unscoped file task must not borrow a code workspace")

    runtime.dispatch.native_executor.workspace_factory = forbidden
    try:
        conversation = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", conversation["id"], "创建并交付报告", key="file", record_intent=True
        )
        await runtime.start()
        await until(
            store,
            lambda db: row(
                db, "SELECT id FROM tasks WHERE id=? AND state='waiting_user'", (task["id"],)
            ),
        )
        updated = await runtime.tasks.get("alice", task["id"])
        binding = json.loads(updated["task"]["target_json"])
        directory = Path(binding["workdir"])
        assert directory.is_relative_to(store.data_root / "agents" / "task-directories")
        assert directory.name == task["id"] and directory != tmp_path
        assert all(value == str(directory) for value in selected)
        assert (directory / "report.md").read_text() == "任务目录可写"
        artifacts = await runtime.artifacts.list("alice", task_id=task["id"])
        assert len(artifacts) == 1 and artifacts[0]["name"] == "report.md"
        assert (await runtime.artifacts.read("alice", artifacts[0]["id"]))[
            1
        ].decode() == "任务目录可写"
        assert not await store.call(
            lambda db: row(db, "SELECT id FROM tool_calls WHERE state='failed'")
        )
    finally:
        await runtime.close()


async def test_directories_are_independent_and_continuation_preserves_outputs(tmp_path):
    first = await prepare_task_directory(tmp_path, "first")
    folder = Path(first["directory"])
    (folder / "draft.txt").write_text("keep this")
    second = await prepare_task_directory(tmp_path, "second")
    again = await prepare_task_directory(tmp_path, "first")
    assert first == again and first["directory"] != second["directory"]
    assert (folder / "draft.txt").read_text() == "keep this"
    assert folder.stat().st_mode & 0o777 == 0o700
    assert folder.parent.parent.stat().st_mode & 0o777 == 0o700
    assert not list(folder.glob(".write-probe-*"))


@pytest.mark.parametrize("component", ["root", "task"])
async def test_directory_symlinks_cannot_redirect_writes(tmp_path, component):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "agents" / "task-directories"
    root.parent.mkdir()
    if component == "root":
        root.symlink_to(outside, target_is_directory=True)
    else:
        root.mkdir()
        (root / "one").symlink_to(outside, target_is_directory=True)
    with pytest.raises(DomainError, match="TASK_DIRECTORY_UNAVAILABLE"):
        await prepare_task_directory(tmp_path, "one")
    assert not list(outside.iterdir())


async def test_continuation_reuses_private_directory_without_claiming_a_code_workspace(store):
    runtime = Runtime(store, ConversationModel(), settings=Settings(workers=0))
    try:
        c = await runtime.conversations.create("alice")
        task = await runtime.tasks.create(
            "alice", c["id"], "Create draft", key="first", record_intent=True
        )
        workspace = await prepare_task_directory(store.data_root, task["id"])
        (Path(workspace["directory"]) / "draft.txt").write_text("original")
        await mark(runtime, task, "waiting_user", {"state": "succeeded", "inputStopped": True})
        await store.call(
            lambda db: db.execute(
                "UPDATE tasks SET target_json=? WHERE id=?",
                (
                    json.dumps(
                        {
                            "workspaceId": workspace["workspaceId"],
                            "workdir": workspace["directory"],
                            "workspace": workspace,
                        }
                    ),
                    task["id"],
                ),
            ),
            write=True,
        )
        await runtime.tasks.revisions.request("alice", task["id"], "Continue draft", 1, "continue")
        await runtime.tasks.revisions.advance()
        current = (await runtime.tasks.get("alice", task["id"]))["task"]
        assert current["revision"] == 2
        assert json.loads(current["intent_json"])["target"] == {"kind": "new_session"}
        again = await prepare_task_directory(store.data_root, current["id"])
        assert again == workspace
        assert (Path(again["directory"]) / "draft.txt").read_text() == "original"
    finally:
        await runtime.close()
