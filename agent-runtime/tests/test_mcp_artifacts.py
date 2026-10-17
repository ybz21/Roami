"""Mixed MCP content is retained without putting binary payloads in prompts."""

import base64
import json

import pytest
from mcp import types

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.artifact_store import ArtifactStore
from roami_agent.tools.mcp_results import MCPResults


async def test_mixed_resource_audio_image_and_large_structured_output_is_recoverable(store):
    artifacts = ArtifactStore(store)
    try:
        raw = b"private binary evidence"
        data = base64.b64encode(raw).decode()
        text = "项目结果" * 8000
        structured = {"entries": ["outcome" * 1000] * 10}
        answer = types.CallToolResult(
            content=[
                types.TextContent(type="text", text=text),
                types.ImageContent(type="image", data=data, mimeType="image/png"),
                types.AudioContent(type="audio", data=data, mimeType="audio/wav"),
                types.EmbeddedResource(
                    type="resource",
                    resource=types.BlobResourceContents(
                        uri="fixture://binary", blob=data, mimeType="application/octet-stream"
                    ),
                ),
                types.EmbeddedResource(
                    type="resource",
                    resource=types.TextResourceContents(
                        uri="fixture://text", text="embedded text", mimeType="text/plain"
                    ),
                ),
                types.ResourceLink(
                    type="resource_link", uri="https://invalid.example/file", name="Reference only"
                ),
            ],
            structuredContent=structured,
        )
        result = await MCPResults(artifacts).project(answer, {"owner": "alice"}, "docs", "read")
        assert len(encoded(result).encode()) < 16_000
        assert data not in encoded(result) and result["structuredContent"] is None
        assert len(result["artifactRefs"]) == 7
        recovered = {}
        for reference in result["artifactRefs"]:
            _, body = await artifacts.read("alice", reference["id"])
            recovered[reference["metadata"]["kind"]] = body
        assert recovered["image"] == recovered["audio"] == raw
        assert recovered["text"].decode() == text
        assert json.loads(recovered["structured"]) == structured
        assert json.loads(recovered["resource_link"])["uri"] == "https://invalid.example/file"
        retry = await MCPResults(artifacts).project(answer, {"owner": "alice"}, "docs", "read")
        assert retry == result
    finally:
        await artifacts.close()


async def test_invalid_binary_and_missing_owner_do_not_publish_references(store):
    artifacts = ArtifactStore(store, max_bytes=8)
    try:
        results = MCPResults(artifacts)
        invalid = types.CallToolResult(
            content=[types.ImageContent(type="image", data="????", mimeType="image/png")]
        )
        with pytest.raises(DomainError, match="MCP_ARTIFACT_STORE_REQUIRED"):
            await results.project(invalid, {}, "docs", "image")
        with pytest.raises(DomainError, match="MCP_INVALID_BINARY_RESULT"):
            await results.project(invalid, {"owner": "alice"}, "docs", "image")
        oversized = types.CallToolResult(
            content=[
                types.ImageContent(
                    type="image", data=base64.b64encode(b"x" * 9).decode(), mimeType="image/png"
                )
            ]
        )
        with pytest.raises(DomainError, match="ARTIFACT_SIZE_LIMIT"):
            await results.project(oversized, {"owner": "alice"}, "docs", "image")
        assert await artifacts.list("alice") == []
    finally:
        await artifacts.close()
