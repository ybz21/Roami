"""Exercise real tmux, Go receipts and Python revisions without a model service."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from roami_agent.conversation.transcript import Conversations
from roami_agent.dispatch.tasks import Tasks
from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import Database, row


async def main():
    binary, root = sys.argv[1], Path(sys.argv[2])
    bins = root / "bin"
    bins.mkdir()
    fixture = Path(__file__).with_name("persistent_provider.py")
    python = sys.executable
    for kind in ["codex", "claude"]:
        script = bins / kind
        script.write_text(f"#!{python}\n" + fixture.read_text())
        script.chmod(0o700)
    os.environ["PATH"] = str(bins) + os.pathsep + os.environ["PATH"]
    database = Database(root / "python/runtime.db", root / "python", managed=False)
    await database.open()
    tasks = Tasks(database, Conversations(database))
    executor = CodingExecutor(database, Settings(cli_bin=binary))
    results = []

    def cli(*args, spec=None):
        response = subprocess.run(
            [binary, "agent", "execution", *args],
            input=json.dumps(spec) if spec else None,
            text=True,
            capture_output=True,
            check=False,
        )
        if response.returncode:
            raise RuntimeError(response.stderr)
        return json.loads(response.stdout)

    async def wait(predicate):
        async with asyncio.timeout(30):
            while not predicate():
                await asyncio.sleep(0.1)

    try:
        for provider in ["codex", "claude"]:
            work = root / provider
            work.mkdir()
            cid = (await tasks.conversations.create("alice"))["id"]
            task = await tasks.create(
                "alice",
                cid,
                "Create initial design",
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
            await database.call(
                lambda db, task=task: db.execute(
                    "UPDATE tasks SET state='preparing' WHERE id=?", (task["id"],)
                ),
                write=True,
            )
            await executor.run(task, run)
            await wait(
                lambda run=run: cli("status", "--key", run["launch_id"])["state"] == "succeeded"
            )
            status = cli("status", "--key", run["launch_id"])
            sid, provider_id = status["session"], status["sessionBinding"]["providerConversationId"]
            assert status["result"]["summary"] == f"{provider}: retained context turn 1"
            # Bind the final observation before a user starts editing again.
            await executor.record(task, run, status)
            live = await asyncio.to_thread(
                subprocess.run,
                [binary, "session", "resolve", sid, "--strict", "--json"],
                capture_output=True,
                check=False,
            )
            assert live.returncode == 0
            manual = await asyncio.to_thread(
                subprocess.run,
                [binary, "session", "send", sid, "Hold correction"],
                capture_output=True,
                check=False,
            )
            assert manual.returncode == 0
            await wait(lambda work=work: (work / "held.txt").exists())
            busy = await asyncio.to_thread(
                subprocess.run,
                [binary, "agent", "execution", "close", "--key", run["launch_id"]],
                capture_output=True,
                text=True,
                check=False,
            )
            assert busy.returncode != 0 and "SESSION_NOT_IDLE" in busy.stderr
            (work / "release.txt").touch()
            await wait(lambda work=work: (work / "last-completed.txt").read_text() == "2")
            await database.call(
                lambda db, task=task: db.execute(
                    "UPDATE tasks SET state='waiting_user' WHERE id=?", (task["id"],)
                ),
                write=True,
            )
            await database.call(
                lambda db, run=run, status=status: db.execute(
                    "UPDATE task_attempts SET state='succeeded',result_json=?,finished_ms=1 WHERE id=?",
                    (json.dumps(status["result"]), run["id"]),
                ),
                write=True,
            )
            await tasks.revisions.request(
                "alice", task["id"], "Main follow-up correction", 1, "followup-" + provider
            )
            await tasks.revisions.advance()
            revised = await database.call(
                lambda db, task=task: row(db, "SELECT * FROM tasks WHERE id=?", (task["id"],))
            )
            next_run = await database.call(
                lambda db, task=task: row(
                    db,
                    "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=2",
                    (task["id"],),
                )
            )
            assert json.loads(revised["intent_json"])["target"]["sessionId"] == sid
            await executor.run(revised, next_run)
            await wait(
                lambda next_run=next_run: (
                    cli("status", "--key", next_run["launch_id"])["state"] == "succeeded"
                )
            )
            continued = cli("status", "--key", next_run["launch_id"])
            assert (
                continued["session"] == sid
                and continued["sessionBinding"]["providerConversationId"] == provider_id
            )
            assert continued["result"]["summary"] == f"{provider}: retained context turn 3"
            closed = cli("close", "--key", next_run["launch_id"])
            assert closed["state"] == "closed" and closed["session"] == sid
            assert cli("close", "--key", next_run["launch_id"])["state"] == "closed"
            assert (work / "turn-count.txt").read_text() == "3"
            sentinel = await asyncio.to_thread(
                subprocess.run,
                [os.environ["TMUX_BIN"], "has-session", "-t", "=_roami-test"],
                capture_output=True,
                check=False,
            )
            assert sentinel.returncode == 0
            results.append(
                {
                    "provider": provider,
                    "initialAndFollowupSameSession": True,
                    "sameProviderConversation": True,
                    "manualContextRetained": True,
                    "closedExplicitly": True,
                    "filesPreserved": True,
                }
            )
        print(json.dumps(results), flush=True)
        print("persistent session scenario passed", flush=True)
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
