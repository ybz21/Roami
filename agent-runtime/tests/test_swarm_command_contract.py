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
            plan_view = {key: value for key, value in plan.items() if key != "argv"}
            plan_view["command"] = shlex.join(plan["argv"])
            assert plan_view in help_view["commands"]
            assert all("argv" not in item for item in help_view["commands"])
            assert all(
                shlex.split(item["command"])[1 : 1 + len(path)] == path
                for item in help_view["commands"]
            )
    finally:
        await runtime.close()


async def test_swarm_post_receipt_uses_identity_not_runtime_callbacks(store):
    runtime = Runtime(store, ConversationModel())
    runtime.swarms.chat = None
    conversation = await runtime.conversations.create("alice")
    created = await runtime.swarms.create(
        "alice",
        {
            "name": "Posting",
            "goal": "Share verified progress",
            "mainConversationId": conversation["id"],
            "commandKey": "create-posting",
        },
    )
    accepted = await runtime.conversations.accept(
        "alice", conversation["id"], "post", "Share verified progress in the group"
    )
    job = await store.call(
        lambda db: row(
            db, "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?", (accepted["turnId"],)
        )
    )
    turn = await runtime.mailbox.claim(job)
    binding = {
        "owner": "alice",
        "conversation": conversation["id"],
        "turnId": turn["id"],
        "leaseEpoch": turn["lease_epoch"],
        "toolCallId": "post-call",
        "assistantMessageId": "message-one",
        "progress": lambda *_: None,
    }
    call = command(
        [
            "roami",
            "swarm",
            "post",
            "--input",
            json.dumps({"swarmId": created["id"], "text": "Plan reviewed"}),
        ],
        as_text=True,
    )
    try:
        posted = await runtime.tools.invoke(call, "main", binding)
        assert (
            await runtime.tools.invoke(
                call,
                "main",
                {**binding, "progress": lambda *_: None, "assistantMessageId": "message-two"},
            )
            == posted
        )
        posts = (await runtime.swarms.snapshot("alice", created["id"]))["posts"]
        assert len(posts) == 1 and posts[0]["author"] == "main"
        other = await runtime.conversations.create("alice")
        with pytest.raises(DomainError, match="REQUEST_KEY_CONFLICT"):
            await runtime.tools.invoke(call, "main", {**binding, "conversation": other["id"]})
        assert len((await runtime.swarms.snapshot("alice", created["id"]))["posts"]) == 1
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


async def test_cli_leader_steering_records_the_same_member_thread_and_preserves_identity(store):
    runtime = Runtime(store, ConversationModel())
    try:
        conversation = await runtime.conversations.create("alice")
        created = await runtime.swarms.create(
            "alice",
            {
                "name": "Persistent team",
                "goal": "Keep source evidence",
                "mainConversationId": conversation["id"],
                "commandKey": "create-team",
            },
        )
        await runtime.swarms.plan(
            "alice",
            created["id"],
            {
                "commandKey": "plan",
                "expectedRevision": 1,
                "items": [
                    {
                        "member": "researcher",
                        "executor": "native",
                        "title": "Research",
                        "goal": "Find facts",
                        "acceptance": "Actual sources",
                    }
                ],
            },
        )
        await runtime.swarms.advance({"aggregate_id": created["id"], "id": "advance"})
        work = (await runtime.swarms.snapshot("alice", created["id"]))["work"][0]
        original = await runtime.tasks.get("alice", work["task_id"])
        old_run = await store.call(
            lambda db: row(db, "SELECT * FROM task_attempts WHERE task_id=?", (work["task_id"],))
        )
        await runtime.dispatch.complete(
            original["task"],
            old_run,
            {"state": "succeeded", "summary": "Original evidence"},
            "succeeded",
        )
        accepted = await runtime.conversations.accept(
            "alice",
            conversation["id"],
            "follow-up",
            "Check the second source, without publishing anything.",
        )
        job = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM jobs WHERE kind='turn.run' AND aggregate_id=?",
                (accepted["turnId"],),
            )
        )
        await runtime.mailbox.claim(job)
        binding = {
            "owner": "alice",
            "conversation": conversation["id"],
            "turnId": accepted["turnId"],
            "toolCallId": "forward",
        }
        payload = {
            "taskId": work["task_id"],
            "revision": 1,
            "text": "Check second source and publish",
            "sourceQuote": "Check the second source, without publishing anything.",
            "requestComplete": True,
        }
        operation = await runtime.tools.invoke(
            command(["roami", "agent", "task", "steer", "--input", json.dumps(payload)]),
            "main",
            binding,
        )
        assert operation["acceptedOnly"] and operation["taskId"] == work["task_id"]
        posts = (await runtime.swarms.snapshot("alice", created["id"]))["posts"]
        forwarded = [post for post in posts if post["author"] == "main"]
        assert len(forwarded) == 1 and forwarded[0]["taskId"] == work["task_id"]
        assert forwarded[0]["text"] == payload["sourceQuote"]
        assert forwarded[0]["deliveryState"] == "accepted"
        await runtime.tasks.revisions.advance()
        current = await runtime.tasks.get("alice", work["task_id"])
        assert current["task"]["revision"] == 2
        new_run = await store.call(
            lambda db: row(
                db,
                "SELECT * FROM task_attempts WHERE task_id=? ORDER BY attempt_no DESC LIMIT 1",
                (work["task_id"],),
            )
        )
        assert new_run["native_branch_id"] == old_run["native_branch_id"]
        assert len(await runtime.tasks.list("alice")) == 1
        assert len((await runtime.swarms.snapshot("alice", created["id"]))["work"]) == 1
    finally:
        await runtime.close()
