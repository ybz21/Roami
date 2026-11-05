"""Ordinary CLI syntax keeps managed scope and never falls through to a shell."""

import json
import shlex

import pytest
from test_argument_repair_progress import claimed_turn
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import rows
from roami_agent.storage.transcript_repository import message
from roami_agent.tools.command_families import COMMANDS


def bash(command):
    return {
        "id": "cli",
        "function": {"name": "bash", "arguments": json.dumps({"command": command})},
    }


async def test_plain_reminder_commands_create_list_cancel_in_bound_conversation(store, monkeypatch):
    async def never_execute(*args, **kwargs):
        pytest.fail("Registered operations must use their bound handler, not a subprocess")

    monkeypatch.setattr("roami_agent.tools.foundations.execute", never_execute)
    runtime = Runtime(store, ConversationModel())
    try:
        turn = await claimed_turn(runtime)
        binding = {
            "owner": "alice",
            "conversation": turn["conversation_id"],
            "turnId": turn["id"],
            "toolCallId": "create",
        }
        text = "Review work\nPreserve '$HOME' and ; | as text"
        created = await runtime.tools.invoke(
            bash(
                shlex.join(
                    ["roami", "agent", "reminder", "add", "--text", text, "--after-seconds=60"]
                )
            ),
            "main",
            binding,
        )
        assert created["spec"]["text"] == text
        listed = await runtime.tools.invoke(bash("roami agent reminder ls"), "main", binding)
        assert [item["id"] for item in listed["reminders"]] == [created["id"]]
        other = await runtime.conversations.create("alice")
        assert not (
            await runtime.tools.invoke(
                bash("roami agent reminder ls"), "main", {**binding, "conversation": other["id"]}
            )
        )["reminders"]
        with pytest.raises(DomainError):
            await runtime.tools.invoke(
                bash("roami agent reminder cancel --id " + created["id"]),
                "main",
                {**binding, "conversation": other["id"]},
            )
        cancelled = await runtime.tools.invoke(
            bash("roami agent reminder cancel --id " + created["id"]), "main", binding
        )
        assert cancelled["enabled"] is False
    finally:
        await runtime.close()


@pytest.mark.parametrize("role", ["main", "worker", "research"])
async def test_flags_json_and_catalog_use_the_same_operation_schema(store, role):
    runtime = Runtime(store, ConversationModel())
    try:
        for command in [
            "roami agent reminder ls",
            "roami agent reminder ls --input '{}'",
            "roami agent reminder ls --input='{}'",
        ]:
            tool, args = runtime.tools.validate(bash(command), role)
            assert tool.name == "reminder_list" and args == {}
        tool, args = runtime.tools.validate(
            bash("roami agent task status --task-id actual --include-result=false"), role
        )
        assert tool.name == "task_status" and args == {"taskId": "actual", "includeResult": False}
        tool, args = runtime.tools.validate(bash("roami agent task status --include-result"), role)
        assert args == {"includeResult": True}
        commands = runtime.tools.directory.command_entries(role)[0]["commands"]
        listing = next(
            item for item in commands if item["argv"] == ["roami", *COMMANDS["reminder_list"]]
        )
        assert listing["inputSchema"]["properties"] == {}
        create = next(item for item in commands if item["argv"][1:4] == COMMANDS["reminder_create"])
        assert create["argv"] == ["roami", "agent", "reminder", "add", "--text", "text"]
        assert create["options"]["--daily-at"]["type"] == "string"
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "suffix",
    [
        "--id private --id duplicate",
        "--id private --conversation other",
        "--id private --key forged",
        "--id private | head",
        "--id private > /tmp/forbidden",
        "--id private; echo done",
        "--id private --input '{}'",
        "--input='[]'",
    ],
)
async def test_invalid_registered_syntax_returns_usage_without_effects(store, suffix):
    runtime = Runtime(store, ConversationModel())
    try:
        turn = await claimed_turn(runtime)
        call = bash("roami agent reminder cancel " + suffix)
        mid = await store.call(
            lambda db: message(
                db,
                turn["conversation_id"],
                turn["branch_id"],
                "assistant",
                {"text": "", "tool_calls": [call]},
                turn_id=turn["id"],
            ),
            write=True,
        )
        result = await runtime.gateway.invoke(turn, mid, call, "main", {"owner": "alice"})
        assert result["error"] == "INVALID_CLI_ARGUMENTS"
        assert result["executionStarted"] is False
        assert result["expectedCommand"]["command"] == "roami agent reminder cancel --id id"
        assert "private" not in json.dumps(result)
        assert not await store.call(lambda db: rows(db, "SELECT * FROM reminder_schedules"))
        events = await runtime.conversations.events("alice", turn["conversation_id"])
        completed = next(event for event in events if event["kind"] == "tool.completed")
        assert completed["payload"]["activity"]["executionStarted"] is False
    finally:
        await runtime.close()


async def test_native_flags_retain_disabled_capability_checks(store):
    runtime = Runtime(store, ConversationModel())
    try:
        runtime.tools.disabled_tools.add("reminder_list")
        with pytest.raises(DomainError, match="TOOL_DISABLED|TOOL_UNAVAILABLE"):
            await runtime.tools.invoke(bash("roami agent reminder ls"), "main", {})
    finally:
        await runtime.close()
