"""Native shell syntax reaches bash without parsing heredoc data as CLI words."""

import pytest
from test_foundations import call
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.server.configuration import Settings


@pytest.mark.parametrize("role", ["main", "worker"])
async def test_heredoc_python_quotes_execute_in_bound_workspace(store, tmp_path, role):
    runtime = Runtime(store, ConversationModel(), settings=Settings(shell_roots=(tmp_path,)))
    command = "python3 - <<'PY'\nprint('can\\'t')\nprint('roami agent task status')\nPY"
    try:
        result = await runtime.tools.invoke(
            call("bash", {"command": command}),
            role,
            {"owner": "alice", "workspace": {"directory": str(tmp_path)}},
        )
        assert result["exitCode"] == 0
        assert result["stdout"] == "can't\nroami agent task status\n"
        assert result["stderr"] == ""
    finally:
        await runtime.close()


async def test_native_shell_syntax_failure_is_an_execution_result(store, tmp_path):
    runtime = Runtime(store, ConversationModel(), settings=Settings(shell_roots=(tmp_path,)))
    try:
        result = await runtime.tools.invoke(
            call("bash", {"command": "printf 'unfinished"}),
            "worker",
            {"owner": "alice", "workspace": {"directory": str(tmp_path)}},
        )
        assert result["exitCode"] == 2
        assert "unexpected EOF" in result["stderr"]
    finally:
        await runtime.close()


@pytest.mark.parametrize(
    "command,expected",
    [
        (r'''printf '%s' "a\"b"''', 'a"b'),
        (
            "cat <<'EOF'\n" + r'''"a\"b"''' + "\nroami agent task status\nEOF",
            r'''"a\"b"''' + "\nroami agent task status\n",
        ),
    ],
)
async def test_escaped_native_quotes_are_data_not_a_model_failure(
    store, tmp_path, command, expected
):
    runtime = Runtime(store, ConversationModel(), settings=Settings(shell_roots=(tmp_path,)))
    try:
        result = await runtime.tools.invoke(
            call("bash", {"command": command}),
            "worker",
            {"owner": "alice", "workspace": {"directory": str(tmp_path)}},
        )
        assert result["exitCode"] == 0 and result["stdout"] == expected
    finally:
        await runtime.close()


async def test_invalid_registered_json_does_not_abort_the_turn(store):
    from test_cli_arguments import claimed_turn

    from roami_agent.protocol.tool_batches import invalid_ending_batch
    from roami_agent.storage.database import row
    from roami_agent.storage.transcript_repository import message

    runtime = Runtime(store, ConversationModel())
    try:
        turn = await claimed_turn(runtime)
        invocation = call("bash", {"command": r'''roami project okr update --input "a\"b"'''})
        assert not invalid_ending_batch(
            runtime.tools, [invocation, call("tool_list", {"query": "project"})], "main"
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
        state = await store.call(
            lambda db: row(db, "SELECT state FROM turns WHERE id=?", (turn["id"],))
        )
        assert state["state"] == "running"
    finally:
        await runtime.close()
