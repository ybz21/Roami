"""Recover the exact provider, including a proven preinput failure, on disposable servers."""

import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.runner import TaskDispatcher
from roami_agent.dispatch.tasks import Tasks
from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import Database, row


async def main():
    binary, root = sys.argv[1], Path(sys.argv[2])
    bins = root / "bin"
    bins.mkdir()
    fixture = Path(__file__).with_name("persistent_provider.py")
    for kind in ["codex", "claude"]:
        script = bins / kind
        script.write_text(f"#!{sys.executable}\n" + fixture.read_text())
        script.chmod(0o700)
    transcripts = root / "provider-transcripts"
    os.environ.update(
        PATH=str(bins) + os.pathsep + os.environ["PATH"],
        CODEX_HOME=str(transcripts / "codex"),
        CLAUDE_CONFIG_DIR=str(transcripts / "claude"),
    )
    database = Database(root / "python/runtime.db", root / "python", managed=False)
    await database.open()
    tasks = Tasks(database, Conversations(database))
    executor = CodingExecutor(database, Settings(cli_bin=binary))
    dispatcher = TaskDispatcher(database, tasks, executor, None, None, asyncio.Event(), {})

    def cli(*args, spec=None):
        response = subprocess.run(
            [binary, *args],
            input=json.dumps(spec) if spec else None,
            text=True,
            capture_output=True,
            check=False,
        )
        if response.returncode:
            raise RuntimeError(response.stderr)
        return json.loads(response.stdout)

    async def observed(run, expected):
        async with asyncio.timeout(30):
            while True:
                status = cli("agent", "execution", "status", "--key", run["launch_id"])
                if status.get("result"):
                    assert status["state"] == expected, status
                    return status
                await asyncio.sleep(0.1)

    async def settle(task, run, status):
        await executor.record(task, run, status)
        await tasks.report(
            "alice", task["id"], run["id"], run["task_revision"], executor.result(status)
        )
        job = await database.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE kind='task.verify' AND aggregate_id=? AND json_extract(payload_json,'$.runId')=?",
                (task["id"], run["id"]),
            )
        )
        await dispatcher.verify(job)
        current = await database.call(
            lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],))
        )
        if current["state"] == "waiting_user":
            # Explicit fixture user acceptance is separate from the provider's report.
            await dispatcher.confirm(
                "alice", task["id"], True, revision=run["task_revision"], run_id=run["id"]
            )
        else:
            assert current["state"] == "failed", current

    async def next_round(task, text, revision):
        await tasks.revisions.request(
            "alice", task["id"], text, revision, f"revision-{revision + 1}-{task['id']}"
        )
        await tasks.revisions.advance()
        task = await database.call(
            lambda db: row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],))
        )
        run = await database.call(
            lambda db: row(
                db,
                "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
                (task["id"], revision + 1),
            )
        )
        assert task["revision"] == revision + 1
        result = await executor.run(task, run)
        assert result is None, result
        return task, run

    results = []
    try:
        for provider in ["codex", "claude"]:
            work = root / provider
            work.mkdir()
            cid = (await tasks.conversations.create("alice"))["id"]
            task = await tasks.create(
                "alice",
                cid,
                "Create initial reference",
                key=provider,
                executor=provider,
                target={"kind": "new_session", "directory": str(work)},
                record_intent=True,
            )
            run = await database.call(
                lambda db, task=task: row(
                    db, "SELECT * FROM task_attempts WHERE task_id=?", (task["id"],)
                )
            )
            assert await executor.run(task, run) is None
            original = await observed(run, "succeeded")
            await settle(task, run, original)
            sid = original["session"]
            provider_id = original["sessionBinding"]["providerConversationId"]
            assert (
                original["result"]["outcomeKnown"] is True
                and original["result"]["inputStopped"] is True
            )
            cli("session", "resolve", sid, "--strict", "--json")
            await asyncio.to_thread(
                subprocess.run,
                [binary, "session", "kill", sid, "--yes"],
                check=True,
                capture_output=True,
            )
            (work / "deny-restore.txt").touch()
            task, failed_run = await next_round(task, "Continue the original reference", 1)
            failed = await observed(failed_run, "failed")
            assert failed["result"]["executionStarted"] is False
            assert (
                failed["result"]["inputStopped"] is True
                and failed["result"]["outcomeKnown"] is True
            )
            await settle(task, failed_run, failed)
            (work / "deny-restore.txt").unlink()
            task, resumed_run = await next_round(
                task, "Retry after the temporary provider failure is resolved", 2
            )
            restored = await observed(resumed_run, "succeeded")
            assert restored["session"] != sid
            assert restored["sessionBinding"]["providerConversationId"] == provider_id
            assert restored["workspace"] == original["workspace"]
            with sqlite3.connect(f"file:{root}/database/meta.db?mode=ro", uri=True) as metadata:
                assert (
                    metadata.execute(
                        "SELECT restored_from FROM sessions WHERE id=?", (restored["session"],)
                    ).fetchone()[0]
                    == sid
                )
                assert (
                    metadata.execute("SELECT status FROM sessions WHERE id=?", (sid,)).fetchone()[0]
                    == "dead"
                )
            assert restored["result"]["summary"] == f"{provider}: retained context turn 2"
            await settle(task, resumed_run, restored)
            launch_dir = Path(os.environ["ROAMI_DATA"]) / "agents/executions"
            spec = json.loads(
                (
                    launch_dir
                    / hashlib.sha256(resumed_run["launch_id"].encode()).hexdigest()
                    / "spec.json"
                ).read_text()
            )
            replay = cli("agent", "execution", "launch", "--file", "-", spec=spec)
            assert replay["session"] == restored["session"]
            assert (work / "turn-count.txt").read_text() == "2"
            task, final_run = await next_round(task, "Review the preserved reference context", 3)
            final = await observed(final_run, "succeeded")
            assert final["session"] == restored["session"]
            assert final["sessionBinding"]["providerConversationId"] == provider_id
            assert final["workspace"] == original["workspace"]
            assert final["result"]["summary"] == f"{provider}: retained context turn 3"
            await settle(task, final_run, final)
            cli("agent", "execution", "close", "--key", final_run["launch_id"])
            results.append(
                {
                    "provider": provider,
                    "originalContext": provider_id,
                    "physicalSessionChangedOnce": True,
                    "providerTurns": 3,
                    "taskRevisions": 4,
                    "preinputFailureRetainedContext": True,
                    "sameWorkspace": True,
                    "replayDidNotExecute": True,
                }
            )
        print(json.dumps(results), flush=True)
        print("provider recovery scenario passed", flush=True)
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
