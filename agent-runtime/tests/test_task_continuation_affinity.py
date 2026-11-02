"""A follow-up cannot become another provider's task in the original workspace."""

import json

import pytest
from test_routing_policy import request, setup

from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.task_continuation import continuation_candidates


async def seed(runtime, binding, directory, *, executor="codex", state="waiting_user"):
    task = await runtime.tasks.create(
        "alice",
        binding["conversation"],
        "用 Codex 做 OKR 产品与技术设计稿",
        title="OKR 设计稿",
        key="original-design",
        executor=executor,
        target={"kind": "project", "projectId": "roami"},
        record_intent=True,
    )
    target = {
        "nodeId": "local",
        "projectId": "roami",
        "workspaceId": "design-workspace",
        "workdir": str(directory),
        "sessionId": "original-session",
    }

    def finish(db):
        db.execute(
            "UPDATE tasks SET state=?,target_json=? WHERE id=?",
            (state, json.dumps(target), task["id"]),
        )
        db.execute(
            "UPDATE task_attempts SET state='succeeded',session_id='original-session',"
            "finished_ms=1,node_id='local',agent_conversation_id='original-provider-conversation',"
            "result_json=? WHERE task_id=?",
            (
                json.dumps(
                    {"state": "succeeded", "summary": "Design files exist", "inputStopped": True}
                ),
                task["id"],
            ),
        )

    await runtime.db.call(finish, write=True)
    return task


async def invoke(tools, name, args, binding, key):
    return await tools.invoke(
        {"function": {"name": name, "arguments": json.dumps(args)}},
        "main",
        {**binding, "toolCallId": key},
    )


@pytest.mark.parametrize("state", ["waiting_user", "succeeded", "failed"])
@pytest.mark.parametrize("executor", ["codex", "claude"])
async def test_followup_preserves_task_provider_and_session(store, state, executor):
    runtime, targets, _, tools, binding = await setup(store, user="产品原型呢，比如在哪设置okr？")
    try:
        directory = store.data_root / "original-worktree"
        directory.mkdir()
        task = await seed(runtime, binding, directory, state=state, executor=executor)
        targets.default = "claude" if executor == "codex" else "codex"
        args = {
            **request(),
            "goal": "补产品原型与设置入口",
            "target": {"kind": "new_session", "directory": str(directory)},
        }
        rejected = await invoke(tools, "delegate", args, binding, "wrong-new-task")
        assert (
            rejected["code"] == "TASK_CONTINUATION_REQUIRED" and rejected["acceptedOnly"] is False
        )
        assert (
            rejected["tasks"][0]["taskId"] == task["id"]
            and rejected["tasks"][0]["executor"] == executor
        )
        assert len(await runtime.tasks.list("alice")) == 1
        receipt = await invoke(
            tools,
            "task_steer",
            {
                "taskId": task["id"],
                "revision": 1,
                "text": "产品原型呢，比如在哪设置okr？",
                "requestComplete": True,
            },
            binding,
            "continue-original",
        )
        assert receipt["acceptedOnly"] is True and receipt["taskId"] == task["id"]
        await runtime.tasks.revisions.advance()
        current = await store.call(
            lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],))
        )
        intent = json.loads(current["intent_json"])
        assert current["revision"] == 2 and intent["executor"] == executor
        assert intent["target"] == {
            "kind": "session",
            "nodeId": "local",
            "sessionId": "original-session",
        }
        assert json.loads(current["target_json"])["workdir"] == str(directory)
        old = await store.call(
            lambda db: row(
                db, "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=1", (task["id"],)
            )
        )
        assert (
            old["session_id"] == "original-session"
            and old["agent_conversation_id"] == "original-provider-conversation"
        )
        launches = []
        coding = CodingExecutor(store, runtime.settings)

        async def command(*args, spec=None):
            launches.append(spec)
            return {"state": "running", "session": "original-session"}

        coding.command = command
        run = await store.call(
            lambda db: row(
                db, "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=2", (task["id"],)
            )
        )
        await coding.run(current, run)
        assert (
            launches[0]["executor"] == executor and launches[0]["sessionId"] == "original-session"
        )
        assert "directory" not in launches[0] and "workspaceId" not in launches[0]
        assert len(await runtime.tasks.list("alice")) == 1 and not targets.sends
    finally:
        await runtime.close()


@pytest.mark.parametrize("target_kind", ["subdirectory", "symlink", "workspace"])
async def test_workspace_aliases_cannot_create_a_replacement(store, target_kind):
    runtime, _, _, tools, binding = await setup(store)
    try:
        directory = store.data_root / "original-worktree"
        directory.mkdir()
        task = await seed(runtime, binding, directory)
        if target_kind == "workspace":
            target = {"kind": "project", "projectId": "roami", "workspaceId": "design-workspace"}
        else:
            path = (
                directory / "docs" if target_kind == "subdirectory" else store.data_root / "alias"
            )
            path.mkdir() if target_kind == "subdirectory" else path.symlink_to(
                directory, target_is_directory=True
            )
            target = {"kind": "new_session", "directory": str(path)}
        result = await invoke(tools, "delegate", {**request(), "target": target}, binding, "alias")
        assert (
            result["code"] == "TASK_CONTINUATION_REQUIRED"
            and result["tasks"][0]["taskId"] == task["id"]
        )
    finally:
        await runtime.close()


async def test_independent_work_keeps_default_routing(store):
    runtime, targets, _, tools, binding = await setup(store)
    try:
        original = store.data_root / "original-worktree"
        original.mkdir()
        await seed(runtime, binding, original)
        targets.default = "claude"
        for number, target in enumerate(
            [
                {"kind": "project", "projectId": "roami"},
                {"kind": "new_session", "directory": str(store.data_root)},
            ]
        ):
            result = await invoke(
                tools, "delegate", {**request(), "target": target}, binding, f"independent-{number}"
            )
            assert result["acceptedOnly"] is True and result["executor"] == "claude"
        assert len(await runtime.tasks.list("alice")) == 3
    finally:
        await runtime.close()


async def test_candidates_exclude_foreign_forgotten_and_other_branches(store):
    runtime, _, _, _, binding = await setup(store)
    try:
        task = await seed(runtime, binding, store.data_root)
        target = {"kind": "new_session", "directory": str(store.data_root)}

        async def find(owner="alice"):
            return await store.call(
                lambda db: continuation_candidates(
                    db, owner, binding["conversation"], binding["turnId"], target
                )
            )

        assert not await find("bob")
        await store.call(
            lambda db: db.execute(
                "INSERT INTO context_omissions(owner_id,message_id,reason,created_ms) VALUES('alice',?,'forgotten_memory_source',1)",
                (task["origin_message_id"],),
            ),
            write=True,
        )
        assert not await find()
        await store.call(lambda db: db.execute("DELETE FROM context_omissions"), write=True)
        other = await runtime.conversations.create("alice")
        await store.call(
            lambda db: db.execute(
                "UPDATE turns SET branch_id=? WHERE id=?",
                (other["active_branch_id"], binding["turnId"]),
            ),
            write=True,
        )
        assert not await find()
    finally:
        await runtime.close()


async def test_missing_session_never_falls_back_to_new_provider(store):
    runtime, _, _, _, binding = await setup(store)
    try:
        task = await seed(runtime, binding, store.data_root)
        await runtime.tasks.revisions.request("alice", task["id"], "补原型", 1, "continue")
        await runtime.tasks.revisions.advance()
        current = await store.call(
            lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],))
        )
        run = await store.call(
            lambda db: row(
                db, "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=2", (task["id"],)
            )
        )
        calls = []
        coding = CodingExecutor(store, runtime.settings)

        async def missing(*args, spec=None):
            calls.append(spec)
            raise DomainError("SESSION_TARGET_NOT_FOUND")

        coding.command = missing
        result = await coding.run(current, run)
        assert result == {"state": "failed", "summary": "SESSION_TARGET_NOT_FOUND"}
        assert (
            len(calls) == 1
            and calls[0]["sessionId"] == "original-session"
            and calls[0]["executor"] == "codex"
        )
    finally:
        await runtime.close()


@pytest.mark.parametrize("state", ["waiting_user", "succeeded", "failed"])
async def test_finished_generic_native_directory_does_not_own_all_its_descendants(store, state):
    runtime, _, _, _, binding = await setup(store)
    try:
        parent = store.data_root / "home"
        child = parent / "documents"
        child.mkdir(parents=True)
        task = await seed(runtime, binding, parent, executor="native", state=state)
        await store.call(
            lambda db: db.execute(
                "UPDATE tasks SET intent_json=json_set(intent_json,'$.target',json(?)),target_json=? WHERE id=?",
                (
                    json.dumps({"kind": "new_session", "directory": str(parent)}),
                    json.dumps({"workdir": str(parent)}),
                    task["id"],
                ),
            ),
            write=True,
        )
        candidates = lambda target: runtime.db.call(
            lambda db: continuation_candidates(
                db, "alice", binding["conversation"], binding["turnId"], target
            )
        )
        assert await candidates({"kind": "new_session", "directory": str(child)}) == []
        assert (await candidates({"kind": "new_session", "directory": str(parent)}))[0][
            "taskId"
        ] == task["id"]
        await store.call(
            lambda db: db.execute(
                "UPDATE task_attempts SET state='unknown' WHERE task_id=?", (task["id"],)
            ),
            write=True,
        )
        assert (await candidates({"kind": "new_session", "directory": str(child)}))[0][
            "taskId"
        ] == task["id"]
    finally:
        await runtime.close()
