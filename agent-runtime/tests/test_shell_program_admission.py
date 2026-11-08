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
