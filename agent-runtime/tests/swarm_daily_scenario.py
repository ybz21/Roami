"""Real installed Go command, Unix HTTP boundary and original Main date-slot flow."""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import uvicorn
from test_runtime import ConversationModel, until

from roami_agent.app import Runtime
from roami_agent.dispatch.swarm_delegations import SwarmDelegations
from roami_agent.server.http import create_app
from roami_agent.storage.database import Database, row


async def run(binary, home, data, socket):
    store = Database(Path(data) / "database/agents/runtime.db", Path(data), managed=False)
    await store.open()
    runtime = Runtime(store, ConversationModel())
    runtime.settings.workers = 0
    server = None
    running = None
    try:
        main = await runtime.conversations.create("local", project_id="daily-project")
        literal = "Continue this original team daily with drafts and data; no external publication in this fixture."
        accepted = await runtime.conversations.accept(
            "local", main["id"], "daily-goal-source", literal
        )
        source_job = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?",
                (accepted["turnId"],),
            )
        )
        source_turn = await runtime.mailbox.claim(source_job)
        binding = {"conversation": main["id"], "turnId": source_turn["id"]}
        team = await runtime.swarms.create(
            "local",
            {
                "name": "Original daily team",
                "goal": literal,
                "mainConversationId": main["id"],
                "target": {"kind": "project", "projectId": "daily-project"},
                "commandKey": "create",
            },
            binding=binding,
        )
        await runtime.swarms.register_members(
            "local",
            team["id"],
            {
                "commandKey": "roles",
                "expectedRevision": 1,
                "members": [
                    {"name": name, "executor": "codex", "duty": "Only this project"}
                    for name in ["X", "Bili", "Data"]
                ],
            },
        )
        original_members = [
            item["id"]
            for item in (await runtime.swarms.snapshot("local", team["id"], include_memory=False))[
                "members"
            ]
        ]
        goal = await SwarmDelegations(store).enable(
            "local",
            team["id"],
            {
                "commandKey": "goal",
                "expectedDelegationRevision": 0,
                "sourceQuote": literal,
                "memberIds": original_members,
            },
            binding=binding,
        )
        message = await runtime.journal.start(source_turn)
        await runtime.journal.finish(
            source_turn, message, "Goal recorded", [], None, 1, final=True, completion=None
        )
        await runtime.start()
        server = uvicorn.Server(
            uvicorn.Config(
                create_app(runtime, manage_lifecycle=False),
                uds=socket,
                log_level="error",
                timeout_graceful_shutdown=2,
            )
        )
        running = asyncio.create_task(server.serve())
        for _ in range(200):
            if server.started:
                break
            if running.done():
                await running
                raise AssertionError("fixture server ended before start")
            await asyncio.sleep(0.01)
        assert server.started
        args = [
            binary,
            "swarm",
            "daily",
            team["id"],
            "--delegation",
            goal["delegationId"],
            "--project",
            "daily-project",
            "--main-conversation",
            main["id"],
            "--timezone",
            "Asia/Shanghai",
            "--date",
            datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
            "--slot",
            "morning",
            "--json",
        ]
        env = {**os.environ, "ROAMI_HOME": home, "ROAMI_DATA": data}
        env["PATH"] = str(Path(binary).parent) + os.pathsep + env.get("PATH", "")
        for key in ["ROAMI_AGENT_CALLER_ROLE", "ROAMI_AGENT_TURN_ID"]:
            env.pop(key, None)

        async def cli(arguments):
            process = await asyncio.create_subprocess_exec(
                *arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
            )
            output, error = await asyncio.wait_for(process.communicate(), timeout=30)
            assert process.returncode == 0, error.decode()
            return json.loads(output)["data"]

        async def skill(*, dry_run=False):
            script = (
                Path(__file__).resolve().parents[2]
                / "skills/okr-development/assets/.roami/okr/skills/daily-operations/scripts/wake_main.py"
            )
            command = [
                sys.executable,
                str(script),
                "--project",
                "daily-project",
                "--conversation",
                main["id"],
                "--swarm",
                team["id"],
                "--delegation",
                goal["delegationId"],
                "--timezone",
                "Asia/Shanghai",
                "--slot",
                "morning",
            ]
            if dry_run:
                command.append("--dry-run")
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
            )
            output, error = await asyncio.wait_for(process.communicate(), timeout=30)
            assert process.returncode == 0, (output.decode(), error.decode())
            return json.loads(output)

        prepared = await skill(dry_run=True)
        assert prepared["state"] == "prepared" and prepared["delivered"] is False
        assert not await store.call(
            lambda db: row(db, "SELECT id FROM jobs WHERE kind='swarm.goal.daily'")
        )
        first = await skill()
        assert first["state"] == "accepted" and first["jobId"]
        replay = await cli(args)
        assert replay["jobId"] == first["jobId"]

        def completed(db):
            return row(
                db,
                "SELECT t.* FROM jobs j JOIN turns t ON t.id=json_extract(j.payload_json,'$.turnId') WHERE j.id=? AND j.state='done' AND t.state='completed'",
                (first["jobId"],),
            )

        await until(store, completed)
        actual = await store.call(completed)
        assert actual["conversation_id"] == main["id"] and actual["trigger_kind"] == "continuation"
        assert (
            await store.call(
                lambda db: db.execute("SELECT count(*) FROM conversations").fetchone()[0]
            )
            == 1
        )
        assert (
            await store.call(
                lambda db: db.execute("SELECT count(*) FROM messages WHERE role='user'").fetchone()[
                    0
                ]
            )
            == 1
        )
        assert (
            await store.call(
                lambda db: db.execute("SELECT count(*) FROM swarm_coordination_batches").fetchone()[
                    0
                ]
            )
            == 1
        )
        after = await runtime.swarms.snapshot("local", team["id"], include_memory=False)
        assert [item["id"] for item in after["members"]] == original_members
        manifest = await store.call(
            lambda db: row(
                db,
                "SELECT parts_json FROM prompt_manifests WHERE turn_id=? ORDER BY attempt_no DESC LIMIT 1",
                (actual["id"],),
            )
        )
        proof = json.loads(manifest["parts_json"])["coordinationEvidence"]
        assert (
            proof["dailySlot"] == first["dailySlot"]
            and proof["sourceMessageId"] == accepted["messageId"]
        )
        print("daily original Main through real Go CLI and Python Unix HTTP passed")
        print("template daily Skill to Go CLI and original Main passed")
    finally:
        if server:
            server.should_exit = True
        if running:
            await running
        await runtime.close()
        await store.close()


if __name__ == "__main__":
    asyncio.run(run(*sys.argv[1:]))
