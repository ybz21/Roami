"""Discovery and help expose the command strings accepted by bash."""

import json
import shlex

import pytest
from test_foundations import call
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.tools import Tool, object_schema


@pytest.mark.parametrize(
    "wrapper",
    [
        "cd /tmp && {command}",
        "cd /tmp;{command}",
        "pwd\n{command}",
        "{command} | head -10",
        "{command}>/tmp/result.json",
        "env EXAMPLE=value {command}",
        r'env LABEL="a\"b" {command}',
        "command {command}",
        "bash -c {quoted}",
    ],
)
async def test_managed_command_wrappers_do_not_run_shell_or_drop_binding(store, wrapper):
    from dataclasses import replace

    runtime, received = Runtime(store, ConversationModel()), []

    async def shell(args, binding):
        raise AssertionError("Wrapped registered operation reached native shell")

    async def lookup(args, binding):
        received.append((args, binding))
        return args

    runtime.tools.registry["shell"] = replace(runtime.tools.registry["shell"], handler=shell)
    runtime.tools.registry["task_status"] = replace(
        runtime.tools.registry["task_status"], handler=lookup
    )
    command = 'roami agent task status --input \'{"taskId":"original-task"}\''
    binding = {"owner": "alice", "conversation": "original-main", "turnId": "original-turn"}
    try:
        args = {"command": wrapper.format(command=command, quoted=shlex.quote(command))}
        with pytest.raises(DomainError, match="INVALID_CLI_ARGUMENTS"):
            await runtime.tools.invoke(call("bash", args), "main", binding)
        assert not received
        hint = runtime.tools.directory.command_hint(args, "main")
        assert hint["expectedCommand"]["command"] == "roami agent task status"
        assert "taskId" in hint["expectedCommand"]["inputSchema"]["properties"]
        assert await runtime.tools.invoke(call("bash", {"command": command}), "main", binding) == {
            "taskId": "original-task"
        }
        assert received[0][1]["conversation"] == "original-main"
        assert received[0][1]["turnId"] == "original-turn"
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "command",
    [
        "printf '%s' 'roami agent task status'",
        "echo roami agent task status",
        "printf '%s' '|' roami agent task status",
        "printf '%s' '&&' roami agent task status",
        "cat <<'EOF'\nroami agent task status\nEOF",
        "python3 collector.py && printf done",
        "roami adb -s example devices",
        "roami chrome text --target example --no-start",
    ],
)
async def test_registered_wrapper_detection_preserves_native_workflows(store, command):
    runtime = Runtime(store, ConversationModel())
    try:
        assert runtime.tools.directory.wrapped_command({"command": command}) is None
    finally:
        await runtime.close()


async def test_wrapped_registered_command_returns_bound_gateway_recovery(store):
    from test_cli_arguments import claimed_turn

    from roami_agent.storage.transcript_repository import message

    runtime = Runtime(store, ConversationModel())
    try:
        turn = await claimed_turn(runtime)
        invocation = call(
            "bash", {"command": "cd /tmp && roami agent reminder cancel --id private | head"}
        )
        mid = await store.call(
            lambda db: message(
                db,
                turn["conversation_id"],
                turn["branch_id"],
                "assistant",
                {"text": "", "tool_calls": [invocation]},
                turn_id=turn["id"],
            ),
            write=True,
        )
        result = await runtime.gateway.invoke(turn, mid, invocation, "main", {"owner": "alice"})
        assert result["error"] == "INVALID_CLI_ARGUMENTS"
        assert result["executionStarted"] is False
        assert "command alone" in result["recovery"]
        assert "do not invent" in result["recovery"]
        assert result["expectedCommand"]["command"] == "roami agent reminder cancel --id id"
        assert "private" not in json.dumps(result)
    finally:
        await runtime.close()


@pytest.mark.parametrize("role", ["main", "worker"])
@pytest.mark.parametrize("prefix,kind", [("mcp", "mcp"), ("cli", "cli"), ("http", "tool")])
async def test_external_command_discovery_round_trips_without_shell_expansion(
    store, role, prefix, kind
):
    runtime, received = Runtime(store, ConversationModel()), []
    name = prefix + "_fixture_lookup"

    async def lookup(args, binding):
        received.append((args, binding["role"]))
        return args

    runtime.tools.add(
        Tool(
            name,
            "Fixture lookup",
            object_schema({"query": {"type": "string"}}, ["query"]),
            lookup,
            main=True,
            source="external",
        )
    )
    try:
        result = await runtime.tools.invoke(
            call("tool_list", {"query": name, "kind": kind}), role, {}
        )
        (entry,) = result["items"]
        assert "command" in entry and "argv" not in entry
        argv = shlex.split(entry["command"])
        assert argv == ["roami", "agent", "capability", "call", name, "--input", "JSON"]
        payload = {"query": "中文 spaces ' quotes $(must-not-execute) ; &"}
        argv[-1] = json.dumps(payload)
        actual = await runtime.tools.invoke(call("bash", {"command": shlex.join(argv)}), role, {})
        assert actual == payload and received == [(payload, role)]
        if kind != "cli":
            alternative = await runtime.tools.invoke(
                call("tool_list", {"query": name, "kind": "cli"}), role, {}
            )
            assert not alternative["items"]
            assert alternative["suggestions"][0]["command"] == entry["command"]
            assert "argv" not in alternative["suggestions"][0]
    finally:
        await runtime.close()


async def test_help_uses_compact_commands_without_mutating_internal_directory(store):
    runtime = Runtime(store, ConversationModel())
    try:
        for role in ("main", "worker"):
            help_view = await runtime.tools.invoke(
                call("bash", {"command": "roami help"}), role, {}
            )
            assert help_view["command"] == "roami help" and "argv" not in help_view
            assert help_view["commands"]
            assert all(
                "command" in entry and "argv" not in entry for entry in help_view["commands"]
            )
            internal = runtime.tools.directory.command_entries(role)[0]
            assert internal["argv"] == ["roami", "help"]
            assert all("argv" in entry and "command" not in entry for entry in internal["commands"])
    finally:
        await runtime.close()


@pytest.mark.parametrize("query", ["task_status", "task status", "roami agent task status"])
async def test_named_builtin_discovery_returns_its_executable_command_and_schema(store, query):
    runtime = Runtime(store, ConversationModel())
    try:
        result = await runtime.tools.invoke(call("tool_list", {"query": query}), "main", {})
        assert (
            result["catalogVersion"] == runtime.tools.directory.list(role="main")["catalogVersion"]
        )
        entry = result["items"][0]
        assert entry["name"] == "task_status" and "commands" not in entry
        argv = shlex.split(entry["command"])
        assert argv == ["roami", "agent", "task", "status"]
        assert "taskId" in entry["inputSchema"]["properties"]
        assert entry["options"]["--task-id"]["type"] == "string"
        conversation = await runtime.conversations.create("alice")
        assert (
            await runtime.tools.invoke(
                call("bash", {"command": shlex.join(argv)}),
                "main",
                {"owner": "alice", "conversation": conversation["id"]},
            )
            == []
        )
    finally:
        await runtime.close()


async def test_named_builtin_discovery_keeps_disabled_and_worker_only_operations_out(store):
    from roami_agent.server.configuration import Settings

    runtime = Runtime(store, ConversationModel(), settings=Settings(browser={"enabled": True}))
    try:
        main = runtime.tools.directory.list("browser_open", role="main")
        assert not any("inputSchema" in item for item in main["items"])
        runtime.tools.disabled_tools.add("task_steer")
        result = await runtime.tools.invoke(call("tool_list", {"query": "task_steer"}), "main", {})
        commands = json.dumps(result)
        assert "roami agent task steer --input" not in commands
        assert "task_steer" not in [entry["name"] for entry in result["items"]]
    finally:
        await runtime.close()


@pytest.mark.parametrize("encoding", ["quoted-command", "argv"])
async def test_structured_json_recovery_preserves_input_and_current_binding(store, encoding):
    from dataclasses import replace

    from test_cli_arguments import claimed_turn

    from roami_agent.storage.transcript_repository import message

    runtime, received = Runtime(store, ConversationModel()), []
    payload = {
        "swarmId": "private-team",
        "taskId": "private-task",
        "revision": 43,
        "runId": "private-run",
        "accepted": True,
        "checks": "中文核验，完整读取本轮三件产物",
        "artifactIds": ["private-first", "private-second"],
    }

    async def verify(args, binding):
        received.append((args, binding))
        return {"received": args}

    runtime.tools.registry["swarm_verify"] = replace(
        runtime.tools.registry["swarm_verify"], handler=verify
    )
    try:
        turn = await claimed_turn(runtime)

        async def invoke(arguments, ident):
            invocation = call("bash", arguments)
            invocation["id"] = ident
            mid = await store.call(
                lambda db: message(
                    db,
                    turn["conversation_id"],
                    turn["branch_id"],
                    "assistant",
                    {"text": "", "tool_calls": [invocation]},
                    turn_id=turn["id"],
                ),
                write=True,
            )
            return await runtime.gateway.invoke(
                turn,
                mid,
                invocation,
                "main",
                {"owner": "alice", "conversation": turn["conversation_id"], "turnId": turn["id"]},
            )

        raw = json.dumps(payload, ensure_ascii=False)
        rejected = await invoke({"command": "roami swarm verify --input " + raw}, "invalid-json")
        assert rejected["error"] == "INVALID_CLI_ARGUMENTS"
        assert rejected["executionStarted"] is False and not received
        assert "single quotes" in rejected["recovery"] and "argv" in rejected["recovery"]
        assert "private" not in json.dumps(rejected)
        argv = ["roami", "swarm", "verify", "--input", raw]
        arguments = (
            {"command": shlex.join(argv)} if encoding == "quoted-command" else {"argv": argv}
        )
        accepted = await invoke(arguments, "corrected-json")
        assert accepted["received"] == payload and len(received) == 1
        assert received[0][1]["conversation"] == turn["conversation_id"]
        assert received[0][1]["turnId"] == turn["id"]
    finally:
        await runtime.close()
