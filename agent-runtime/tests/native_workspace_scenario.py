"""Cross-language scenario invoked by the Go integration test with an isolated instance."""

import asyncio
import json
import os
import sys
from pathlib import Path

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import Database, row


class Main:
    model = "fixture-main"

    async def stream(self, messages, tools):
        yield ModelEvent("text", "Task result received")


class Worker:
    model = "fixture-worker"

    async def stream(self, messages, tools):
        if any(m["role"] == "user" and "write checked file" in m["content"] for m in messages):
            results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
            step = len(results)
            if step == 4:
                assert results[-1]["data"] == "verified"
                yield ModelEvent("text", "Verified the checked workspace file")
                return
            name, args = (
                (
                    "file_write",
                    {"path": "native-file-proof.txt", "expectedSha256": None, "content": "checked"},
                )
                if step == 0
                else (
                    "file_patch",
                    {
                        "path": "native-file-proof.txt",
                        "expectedSha256": results[-1]["sha256"],
                        "oldText": "checked",
                        "newText": "verified",
                    },
                )
                if step == 2
                else ("file_read", {"path": "native-file-proof.txt"})
            )
            yield ModelEvent(
                "tool",
                {
                    "id": "file-" + str(step),
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                },
            )
            return
        if messages[-1]["role"] == "tool":
            result = json.loads(messages[-1]["content"])
            assert result.get("exitCode") == 0, result
            yield ModelEvent("text", "Workspace file written")
            return
        assert "Prepared task workspace (trusted runtime binding)" in messages[0]["content"]
        goal = messages[-1]["content"]
        if "ambiguous" in goal:
            yield ModelEvent(
                "tool",
                {
                    "id": "uncertain",
                    "type": "function",
                    "function": {"name": "ambiguous_write", "arguments": "{}"},
                },
            )
            return
        code = "from pathlib import Path; import os; assert 'GIT_DIR' not in os.environ; Path('native-proof.txt').write_text('native')"
        if "cancel" in goal:
            code = "from pathlib import Path; import os,time; Path('native-pid.txt').write_text(str(os.getpid())); time.sleep(60); Path('late-write.txt').write_text('unexpected')"
        yield ModelEvent(
            "tool",
            {
                "id": "workspace-shell",
                "type": "function",
                "function": {
                    "name": "shell",
                    "arguments": json.dumps({"argv": [sys.executable, "-c", code]}),
                },
            },
        )


class Memory:
    model = "fixture-memory"

    async def stream(self, messages, tools):
        yield ModelEvent("text", '{"memories":[]}')


async def main():
    cli, root, project, directory = sys.argv[1:]
    root, directory = Path(root), Path(directory)
    owner = "native-fixture-" + os.environ.get("ROAMI_FIXTURE_PROJECT_MODE", "existing")
    db = Database(
        root
        / ("native-runtime-" + os.environ.get("ROAMI_FIXTURE_PROJECT_MODE", "existing") + ".db"),
        root,
        managed=False,
    )
    await db.open()

    async def verify(task, result):
        if json.loads(task["intent_json"])["goal"] == "write checked file":
            return (directory / "native-file-proof.txt").read_text() == "verified"
        return (directory / "native-proof.txt").read_text() == "native"

    runtime = Runtime(
        db,
        Main(),
        settings=Settings(cli_bin=cli),
        worker_model=Worker(),
        memory_model=Memory(),
        verifier=verify,
    )

    uncertain_started = asyncio.Event()

    async def ambiguous_write(args, binding):
        uncertain_started.set()
        await asyncio.Event().wait()
        raise DomainError("MCP_OUTCOME_UNKNOWN")

    runtime.tools.add(
        Tool(
            "ambiguous_write",
            "Fixture ambiguous write",
            object_schema({}),
            ambiguous_write,
            effect="write",
        )
    )

    async def wait(predicate):
        async with asyncio.timeout(15):
            while not await predicate():
                await asyncio.sleep(0.03)

    async def terminal(ident, state):
        return await db.call(
            lambda connection: row(
                connection, "SELECT id FROM tasks WHERE id=? AND state=?", (ident, state)
            )
        )

    await runtime.start()
    try:
        c = await runtime.conversations.create(owner)
        new_project = os.environ.get("ROAMI_FIXTURE_PROJECT_MODE") == "new"
        initial_target = (
            {"kind": "new_project", "name": directory.name, "baseDir": str(directory.parent)}
            if new_project
            else {"kind": "project", "projectId": project}
        )
        task = await runtime.tasks.create(
            owner,
            c["id"],
            "write proof",
            key="native-project",
            target=initial_target,
            record_intent=True,
        )

        async def initial_done():
            current = await db.call(
                lambda connection: row(
                    connection, "SELECT state FROM tasks WHERE id=?", (task["id"],)
                )
            )
            if current["state"] in {"failed", "interrupted", "cancelled"}:
                details = await db.call(
                    lambda connection: row(
                        connection,
                        "SELECT result_json FROM task_attempts WHERE task_id=?",
                        (task["id"],),
                    )
                )
                raise AssertionError(details)
            return current["state"] == "succeeded"

        await wait(initial_done)
        current = (await runtime.tasks.list(owner))[0]
        target = json.loads(current["target_json"])
        assert target["workdir"] == str(directory) and target["workspaceId"]
        project = target["projectId"]
        if new_project:
            from roami_agent.executors.project import provision_project

            run = await db.call(
                lambda connection: row(
                    connection, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],)
                )
            )
            replay = await provision_project(runtime.settings, task, run)
            assert (
                replay["projectId"] == project
                and (directory / "native-proof.txt").read_text() == "native"
            )
            (directory.parent / "elsewhere").mkdir()
            conflict = await runtime.tasks.create(
                owner,
                c["id"],
                "must not overwrite",
                key="conflicting-project",
                target={
                    "kind": "new_project",
                    "name": directory.name,
                    "baseDir": str(directory.parent / "elsewhere"),
                },
                record_intent=True,
            )
            await wait(lambda: terminal(conflict["id"], "failed"))
            assert not (directory.parent / "elsewhere" / directory.name).exists()

        if new_project:
            await runtime.memory.daily.refresh(owner)
            summary = await db.call(
                lambda connection: row(
                    connection,
                    "SELECT counts_json FROM day_summaries WHERE owner_id=? AND scope_key=?",
                    (owner, project),
                )
            )
            assert summary and json.loads(summary["counts_json"])["tasksCreated"] == 1
            assert json.loads(summary["counts_json"])["tasksCompleted"] == 1
            completed = await db.call(
                lambda connection: row(
                    connection,
                    "SELECT id FROM events WHERE task_id=? AND kind='task.succeeded'",
                    (task["id"],),
                )
            )
            _, scope = await db.call(
                lambda connection: runtime.memory_jobs._sources(
                    connection, {"owner": owner, "eventId": completed["id"]}
                )
            )
            assert scope["project_id"] == project
        events = await runtime.conversations.events(owner, c["id"])
        kinds = [event["kind"] for event in events if event["task_id"] == task["id"]]
        assert (
            kinds.index("task.preparing")
            < kinds.index("task.workspace_prepared")
            < kinds.index("task.started")
        )
        if new_project:
            from roami_agent.tools.process import execute

            for argv in [
                ["git", "init", "-b", "main"],
                ["git", "add", "native-proof.txt"],
                [
                    "git",
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "commit",
                    "-m",
                    "initial project",
                ],
            ]:
                assert (await execute(argv, cwd=directory))["exitCode"] == 0
        steering = await runtime.tasks.revisions.request(
            owner, task["id"], "Inspect and retain the existing proof", 1, "native-steer"
        )

        async def continued_done():
            current = await db.call(
                lambda connection: row(
                    connection,
                    "SELECT revision,state,target_json FROM tasks WHERE id=?",
                    (task["id"],),
                )
            )
            operation = await runtime.tasks.revisions.get(
                owner, task["id"], steering["operationId"]
            )
            assert operation["state"] != "blocked", operation
            return current["revision"] == 2 and current["state"] == "succeeded"

        await wait(continued_done)
        continued = await db.call(
            lambda connection: row(
                connection, "SELECT target_json FROM tasks WHERE id=?", (task["id"],)
            )
        )
        assert json.loads(continued["target_json"])["workspaceId"] == target["workspaceId"]
        assert json.loads(continued["target_json"])["projectId"] == project
        assert (directory / "native-proof.txt").read_text() == "native"
        file_task = await runtime.tasks.create(
            owner,
            c["id"],
            "write checked file",
            key="native-files",
            target={"kind": "project", "projectId": project, "workspaceId": target["workspaceId"]},
            record_intent=True,
        )
        await wait(lambda: terminal(file_task["id"], "succeeded"))
        assert (directory / "native-file-proof.txt").read_text() == "verified"
        cancelling = await runtime.tasks.create(
            owner,
            c["id"],
            "cancel long shell",
            key="native-cancel",
            target={"kind": "project", "projectId": project, "workspaceId": target["workspaceId"]},
            record_intent=True,
        )

        async def child_started():
            return (directory / "native-pid.txt").exists()

        await wait(child_started)
        pid = int((directory / "native-pid.txt").read_text())
        await runtime.tasks.cancel(owner, cancelling["id"])
        await wait(lambda: terminal(cancelling["id"], "cancelled"))
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError("Cancelled native shell is still alive")
        assert not (directory / "late-write.txt").exists()
        again = await runtime.tasks.create(
            owner,
            c["id"],
            "write proof again",
            key="native-again",
            target={"kind": "project", "projectId": project, "workspaceId": target["workspaceId"]},
            record_intent=True,
        )
        await wait(lambda: terminal(again["id"], "succeeded"))
        uncertain = await runtime.tasks.create(
            owner,
            c["id"],
            "ambiguous write",
            key="native-ambiguous",
            target={"kind": "project", "projectId": project, "workspaceId": target["workspaceId"]},
            record_intent=True,
        )
        await asyncio.wait_for(uncertain_started.wait(), 10)
        await runtime.tasks.cancel(owner, uncertain["id"])
        await wait(lambda: terminal(uncertain["id"], "interrupted"))
        details = await db.call(
            lambda connection: row(
                connection,
                "SELECT result_json FROM task_attempts WHERE task_id=?",
                (uncertain["id"],),
            )
        )
        assert json.loads(details["result_json"])["summary"] == "NATIVE_WORKSPACE_OUTCOME_UNKNOWN"
        blocked = await runtime.tasks.create(
            owner,
            c["id"],
            "must not execute",
            key="native-quarantined",
            target={"kind": "project", "projectId": project, "workspaceId": target["workspaceId"]},
            record_intent=True,
        )
        await wait(lambda: terminal(blocked["id"], "failed"))
        attempt = await db.call(
            lambda connection: row(
                connection,
                "SELECT native_branch_id FROM task_attempts WHERE task_id=?",
                (blocked["id"],),
            )
        )
        assert not await db.call(
            lambda connection: row(
                connection,
                "SELECT x.id FROM tool_calls x JOIN turns t ON t.id=x.turn_id WHERE t.branch_id=?",
                (attempt["native_branch_id"],),
            )
        )
        print(
            "native workspace scenario passed: project binding, default shell cwd, confirmation, cancellation, child stop, workspace reuse"
        )
    finally:
        await runtime.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
