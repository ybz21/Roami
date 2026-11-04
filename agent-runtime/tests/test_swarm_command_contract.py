import json
import shlex

import pytest
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row


def command(argv, *, as_text=False):
    args = {"command": shlex.join(argv)} if as_text else {"argv": argv}
    return {"function": {"name": "bash", "arguments": json.dumps(args)}}


async def test_swarm_discovery_and_scoped_help_return_executable_schemas(store):
    runtime = Runtime(store, ConversationModel())
    try:
        directory = runtime.tools.directory.list("swarm", "cli", 20)
        entry = next(item for item in directory["items"] if item["name"] == "roami")
        plan = next(item for item in entry["commands"] if item["argv"][1:3] == ["swarm", "plan"])
        assert set(plan["inputSchema"]["required"]) == {"swarmId", "expectedRevision", "items"}
        assert plan["effect"] == "write"
        assert not any(item["name"] == "swarm_plan" for item in directory["items"])
        for path in [["swarm"], ["swarm", "plan"]]:
            help_view = await runtime.tools.invoke(command(["roami", *path, "help"]), "main", {})
            assert help_view["name"] == "roami " + " ".join(path)
            assert plan in help_view["commands"]
            assert all(item["argv"][1 : 1 + len(path)] == path for item in help_view["commands"])
    finally:
        await runtime.close()


@pytest.mark.parametrize("as_text", [False, True])
async def test_discovered_swarm_commands_preserve_binding_and_revision_without_host_cli(
    store, monkeypatch, as_text
):
    async def no_host_cli(*args, **kwargs):
        raise AssertionError("Registered operations must stay in the bound runtime")

    monkeypatch.setattr("roami_agent.tools.foundations.execute", no_host_cli)
    runtime = Runtime(store, ConversationModel())
    runtime.swarms.chat = None
    conversation = await runtime.conversations.create("alice")
    accepted = await runtime.conversations.accept(
        "alice", conversation["id"], "origin", "Verify media"
    )
    binding = {
        "owner": "alice",
        "conversation": conversation["id"],
        "turnId": accepted["turnId"],
    }
    sequence = 0

    async def invoke(path, payload, *, current=binding):
        nonlocal sequence
        sequence += 1
        return await runtime.tools.invoke(
            command(["roami", *path, "--input", json.dumps(payload)], as_text=as_text),
            "main",
            {**current, "toolCallId": str(sequence)},
        )

    try:
        created = await invoke(
            ["swarm", "new"], {"name": "Media verification", "goal": "Verify actual files"}
        )
        sid = created["id"]
        stopped = await invoke(
            ["swarm", "control"],
            {"swarmId": sid, "expectedRevision": 1, "action": "pause"},
        )
        spec = {
            "swarmId": sid,
            "expectedRevision": stopped["revision"],
            "items": [
                {
                    "member": "preflight",
                    "executor": "codex",
                    "title": "Verify the existing MP4",
                    "goal": "Measure the existing media and write a report without changing inputs",
                    "acceptance": "Actual report with byte size, hash and full decode evidence",
                }
            ],
        }
        await invoke(["swarm", "plan"], spec)
        snapshot = await invoke(["swarm", "status"], {"swarmId": sid})
        assert snapshot["paused"] and len(snapshot["work"]) == 1
        assert snapshot["work"][0]["goal"] == spec["items"][0]["goal"]
        assert snapshot["work"][0]["task_id"] is None
        assert (await store.call(lambda db: row(db, "SELECT count(*) AS n FROM tasks")))["n"] == 0
        with pytest.raises(DomainError, match="SWARM_PLAN_CHANGED"):
            await invoke(["swarm", "plan"], spec)
        other = await runtime.conversations.create("alice")
        with pytest.raises(DomainError, match="SWARM_MAIN_REQUIRED"):
            await invoke(
                ["swarm", "plan"],
                {**spec, "expectedRevision": snapshot["revision"]},
                current={**binding, "conversation": other["id"]},
            )
        assert len((await invoke(["swarm", "status"], {"swarmId": sid}))["work"]) == 1
    finally:
        await runtime.close()
