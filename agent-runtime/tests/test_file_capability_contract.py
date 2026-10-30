"""Foundation reads retain generic byte contracts without document-format dispatch."""

import base64
import hashlib
import json

import pytest
from test_foundations import call
from test_runtime import ConversationModel

from roami_agent.app import Runtime
from roami_agent.protocol.errors import DomainError


async def test_binary_file_reads_preserve_pages_and_source_hash(store, tmp_path):
    body = bytes(range(256)) * 2
    (tmp_path / "input.pptx").write_bytes(body)
    runtime = Runtime(store, ConversationModel())
    binding = {"taskId": "bytes", "workspace": {"directory": str(tmp_path)}}
    try:
        offset, chunks = 0, []
        while True:
            result = await runtime.tools.invoke(
                call("read", {"path": "input.pptx", "offset": offset, "limit": 37}),
                "worker",
                binding,
            )
            assert result["sha256"] == hashlib.sha256(body).hexdigest()
            chunks.append(
                base64.b64decode(result["data"])
                if result["encoding"] == "base64"
                else result["data"].encode()
            )
            if result["nextOffset"] is None:
                break
            offset = result["nextOffset"]
        assert b"".join(chunks) == body
        assert (tmp_path / "input.pptx").read_bytes() == body
    finally:
        await runtime.close()


async def test_document_mode_is_not_a_foundation_file_operation(store, tmp_path, monkeypatch):
    runtime = Runtime(store, ConversationModel())
    reads = []

    async def forbidden(*args, **kwargs):
        reads.append(args)
        raise AssertionError("Format-specific arguments must fail before file access")

    monkeypatch.setattr(runtime.files, "read", forbidden)
    try:
        with pytest.raises(DomainError, match="INVALID_TOOL_ARGUMENTS"):
            await runtime.tools.invoke(
                call("read", {"path": "input.pptx", "view": "document"}),
                "worker",
                {"taskId": "bytes", "workspace": {"directory": str(tmp_path)}},
            )
        assert reads == []
    finally:
        await runtime.close()


async def test_document_workflows_are_optional_not_reserved_builtins(store):
    runtime = Runtime(store, ConversationModel())
    try:
        assert set(runtime.tools.skills) == {"roami", "browser_use"}
        assert not runtime.tools.directory.list("幻灯片", "skill")["items"]
        with pytest.raises(DomainError, match="INVALID_TOOL_ARGUMENTS"):
            await runtime.tools.invoke(
                call("read", {"path": "skill://presentation_files"}), "worker", {}
            )
        schemas = json.dumps(runtime.tools.catalog("worker"))
        assert "view=document" not in schemas
    finally:
        await runtime.close()
