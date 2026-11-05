import json
import sys

import pytest
from test_runtime import ConversationModel
from test_swarm_command_contract import command

from roami_agent.app import Runtime
from roami_agent.server.configuration import Settings
from roami_agent.tools.process import execute


@pytest.mark.parametrize("role", ["main", "worker", "research"])
async def test_real_shell_child_carries_restrictive_role_marker(store, tmp_path, role):
    runtime = Runtime(store, ConversationModel(), settings=Settings(shell_roots=(tmp_path,)))
    try:
        result = await runtime.tools.invoke(
            command(
                [sys.executable, "-c", "import os;print(os.getenv('ROAMI_AGENT_CALLER_ROLE'))"]
            ),
            role,
            {"owner": "alice", "workspace": {"directory": str(tmp_path)}},
        )
        assert result["exitCode"] == 0 and result["stdout"].strip() == role
    finally:
        await runtime.close()


async def test_environment_overrides_cannot_restore_excluded_credentials(tmp_path):
    result = await execute(
        [
            sys.executable,
            "-c",
            "import os;print(os.getenv('ROAMI_AGENT_CALLER_ROLE'));print('ROAMI_FIXTURE_SECRET' in os.environ)",
        ],
        cwd=tmp_path,
        env_overrides={"ROAMI_AGENT_CALLER_ROLE": "main", "ROAMI_FIXTURE_SECRET": "fixture"},
        excluded_env={"ROAMI_FIXTURE_SECRET"},
    )
    assert result["stdout"] == "main\nFalse\n"


async def test_main_registered_post_retains_identity_without_new_turn(store):
    runtime = Runtime(store, ConversationModel())
    conversation = await runtime.conversations.create("alice")
    created = await runtime.swarms.create(
        "alice",
        {
            "name": "Persistent team",
            "goal": "Post verified progress",
            "mainConversationId": conversation["id"],
            "commandKey": "create-team",
        },
    )
    binding = {
        "owner": "alice",
        "conversation": conversation["id"],
        "turnId": "progress-turn",
        "toolCallId": "progress-call",
    }
    prior_posts = (await runtime.swarms.snapshot("alice", created["id"]))["posts"]
    before = await store.call(lambda db: db.execute("SELECT COUNT(*) FROM turns").fetchone()[0])
    try:
        call = command(
            [
                "roami",
                "swarm",
                "post",
                "--input",
                json.dumps({"swarmId": created["id"], "text": "Evidence verified"}),
            ],
            as_text=True,
        )
        first = await runtime.tools.invoke(call, "main", binding)
        assert await runtime.tools.invoke(call, "main", binding) == first
        posts = (await runtime.swarms.snapshot("alice", created["id"]))["posts"]
        assert len(posts) == len(prior_posts) + 1 and posts[-1]["author"] == "main"
        assert (
            await store.call(lambda db: db.execute("SELECT COUNT(*) FROM turns").fetchone()[0])
            == before
        )
    finally:
        await runtime.close()
