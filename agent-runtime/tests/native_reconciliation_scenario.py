"""Actual abandoned Go hold, Python persistence and late stop acknowledgement in private roots."""

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

from test_native_reconciliation import abandoned

from roami_agent.dispatch.resource_leases import ResourceLeases
from roami_agent.executors.native_reconciliation import NativeWorkspaceReconciliation
from roami_agent.server.configuration import Settings
from roami_agent.storage.database import Database, event, row


async def main():
    binary, root, directory = sys.argv[1:]
    root = Path(root)
    database = Database(root / "python/database/agents/runtime.db", root / "python", managed=False)
    await database.open()
    process = None
    try:
        conversation, task, run, turn, _ = await abandoned(database)

        def starting(db):
            db.execute(
                "UPDATE tasks SET state='preparing',intent_json=json_set(intent_json,'$.target.directory',?) WHERE id=?",
                (directory, task["id"]),
            )
            db.execute("UPDATE task_attempts SET state='starting' WHERE id=?", (run["id"],))
            db.execute("UPDATE turns SET state='running' WHERE id=?", (turn,))
            db.execute(
                "UPDATE jobs SET state='running' WHERE aggregate_id=? AND kind='task.run'",
                (task["id"],),
            )

        await database.call(starting, write=True)
        process = await asyncio.create_subprocess_exec(
            binary,
            "agent",
            "execution",
            "hold",
            "--file",
            "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
            start_new_session=True,
        )
        spec = {
            "key": run["launch_id"],
            "executor": "native",
            "directory": directory,
            "timeoutSeconds": 120,
        }
        process.stdin.write((json.dumps(spec) + "\n").encode())
        await process.stdin.drain()
        async with asyncio.timeout(10):
            receipt = json.loads(await process.stdout.readline())
        assert (
            receipt["state"] == "native_running" and receipt["workspace"]["directory"] == directory
        )
        await database.call(
            lambda db: event(
                db,
                conversation["id"],
                "task.workspace_prepared",
                {"taskId": task["id"], "runId": run["id"], "workspace": receipt["workspace"]},
                task_id=task["id"],
                key="workspace:" + run["id"],
            ),
            write=True,
        )
        process.stdin.close()
        async with asyncio.timeout(10):
            await process.wait()
        assert process.returncode != 0
        launch_directory = (
            root / "agents/executions" / hashlib.sha256(run["launch_id"].encode()).hexdigest()
        )
        assert not (launch_directory / "result.json").exists()

        def interrupted(db):
            db.execute("UPDATE tasks SET state='interrupted' WHERE id=?", (task["id"],))
            db.execute("UPDATE task_attempts SET state='unknown' WHERE id=?", (run["id"],))
            db.execute("UPDATE turns SET state='interrupted' WHERE id=?", (turn,))
            db.execute(
                "UPDATE jobs SET state='failed' WHERE aggregate_id=? AND kind='task.run'",
                (task["id"],),
            )

        await database.call(interrupted, write=True)
        database.instance_paths = json.loads((root / "storage-layout.json").read_text())["paths"]
        service = NativeWorkspaceReconciliation(
            database, Settings(cli_bin=binary), resources=ResourceLeases(database)
        )
        await service.tick()
        await service.tick()
        result = json.loads((launch_directory / "result.json").read_text())
        assert (
            result["state"] == "failed"
            and result["inputStopped"] is True
            and result["outcomeKnown"] is False
        )
        current = await database.call(
            lambda db: row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],))
        )
        assert current["state"] == "interrupted"
        entries = await database.call(
            lambda db: db.execute(
                "SELECT payload_json FROM events WHERE event_key=?",
                ("native-workspace-reconciled:" + run["id"],),
            ).fetchall()
        )
        assert (
            len(entries) == 1
            and json.loads(entries[0][0])["evidenceSha256"] == result["stopEvidenceSha256"]
        )
        print(
            "native reconciliation scenario passed: real hold EOF, scoped stop proof, original task preserved, no replay"
        )
    finally:
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
