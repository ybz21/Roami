"""Real process evidence and bounded Worker retrieval share owner-scoped storage."""

import json
import sys

import pytest

from roami_agent.protocol.errors import DomainError
from roami_agent.server.configuration import Settings
from roami_agent.storage.artifact_store import ArtifactStore
from roami_agent.tools.artifacts import register_artifact_tools
from roami_agent.tools.registry import Tools
from roami_agent.tools.shell import register_shell


def call(name, arguments):
    return {"id": "fixture", "function": {"name": name, "arguments": json.dumps(arguments)}}


async def test_large_and_binary_process_output_is_exact_and_excerpts_are_bounded(store, tmp_path):
    artifacts = ArtifactStore(store)
    tools = Tools()
    register_shell(tools, Settings(shell_roots=(tmp_path,)), artifacts)
    register_artifact_tools(tools, artifacts)
    try:
        result = await tools.invoke(
            call(
                "shell",
                {
                    "cwd": str(tmp_path),
                    "argv": [
                        sys.executable,
                        "-c",
                        "import os; os.write(1, '项目'.encode()*10000); os.write(2,b'\\x00\\xffbinary')",
                    ],
                },
            ),
            "worker",
            {"owner": "alice"},
        )
        assert result["exitCode"] == 0 and result["outputExternalized"]
        assert len(result["stdout"].encode()) <= 4000 and result["stderr"] == ""
        refs = {ref["metadata"]["stream"]: ref for ref in result["artifactRefs"]}
        assert (await artifacts.read("alice", refs["stdout"]["id"]))[1] == "项目".encode() * 10000
        assert (await artifacts.read("alice", refs["stderr"]["id"]))[1] == b"\x00\xffbinary"
        excerpt = await tools.invoke(
            call(
                "artifact_read",
                {
                    "id": refs["stdout"]["id"],
                    "offset": 6,
                    "limit": 12,
                },
            ),
            "worker",
            {"owner": "alice"},
        )
        assert excerpt["text"] == "项目项目" and excerpt["nextOffset"] == 18 and excerpt["hasMore"]
        binary = await tools.invoke(
            call("artifact_read", {"id": refs["stderr"]["id"]}), "worker", {"owner": "alice"}
        )
        assert binary["textAvailable"] is False and "text" not in binary
        with pytest.raises(DomainError, match="ARTIFACT_NOT_FOUND"):
            await tools.invoke(
                call("artifact_read", {"id": refs["stdout"]["id"]}), "worker", {"owner": "bob"}
            )
        assert tools.catalog("main") == []
    finally:
        await artifacts.close()


async def test_small_shell_output_keeps_exit_status_and_separate_streams(store, tmp_path):
    artifacts = ArtifactStore(store)
    tools = Tools()
    register_shell(tools, Settings(shell_roots=(tmp_path,)), artifacts)
    try:
        result = await tools.invoke(
            call(
                "shell",
                {
                    "cwd": str(tmp_path),
                    "argv": [
                        sys.executable,
                        "-c",
                        "import sys; print('stdout'); print('stderr',file=sys.stderr); sys.exit(3)",
                    ],
                },
            ),
            "worker",
            {"owner": "alice"},
        )
        assert result == {"stdout": "stdout\n", "stderr": "stderr\n", "exitCode": 3}
        assert await artifacts.list("alice") == []
    finally:
        await artifacts.close()
