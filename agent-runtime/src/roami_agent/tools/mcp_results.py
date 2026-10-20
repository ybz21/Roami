"""Bound MCP evidence before it enters the model context."""

import base64
import binascii

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded


class MCPResults:
    def __init__(self, artifacts=None):
        self.artifacts = artifacts

    async def project(self, answer, binding, server, remote):
        parts = answer.model_dump(mode="json", by_alias=True, exclude_none=True)["content"]
        result = {
            "content": [part["text"] for part in parts if part["type"] == "text"],
            "structuredContent": answer.structuredContent,
        }
        binary = any(part["type"] != "text" for part in parts)
        if not binary and len(encoded(result).encode()) <= 64_000:
            return result
        if not self.artifacts or not binding.get("owner"):
            raise DomainError("MCP_ARTIFACT_STORE_REQUIRED")
        references, content, budget = [], [], 4000

        async def save(body, mime, name, kind, index):
            references.append(
                await self.artifacts.put(
                    binding["owner"],
                    body,
                    mime_type=mime,
                    name=name,
                    task_id=binding.get("taskId"),
                    message_id=binding.get("assistantMessageId"),
                    metadata={
                        "source": "mcp",
                        "server": server,
                        "tool": remote,
                        "kind": kind,
                        "part": index,
                    },
                )
            )

        for index, part in enumerate(parts):
            kind = part["type"]
            if kind == "text":
                body = part["text"].encode()
                if len(body) > budget:
                    await save(body, "text/plain", f"mcp-{index}.txt", kind, index)
                preview = body[:budget].decode(errors="ignore")
                content.append(preview)
                budget -= len(preview.encode())
                continue
            resource = part.get("resource", {}) if kind == "resource" else part
            data = resource.get("data") if kind in {"image", "audio"} else resource.get("blob")
            if data is not None:
                if (
                    self.artifacts.max_bytes
                    and len(data) > ((self.artifacts.max_bytes + 2) // 3) * 4
                ):
                    raise DomainError("ARTIFACT_SIZE_LIMIT", 413)
                try:
                    body = base64.b64decode(data, validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise DomainError("MCP_INVALID_BINARY_RESULT") from exc
                await save(
                    body,
                    resource.get("mimeType", "application/octet-stream"),
                    f"mcp-{index}.bin",
                    kind,
                    index,
                )
            elif kind == "resource" and isinstance(resource.get("text"), str):
                await save(
                    resource["text"].encode(),
                    resource.get("mimeType", "text/plain"),
                    f"mcp-{index}.txt",
                    kind,
                    index,
                )
            else:
                # Resource links are evidence, never an instruction to fetch another URL.
                await save(
                    encoded(part).encode(), "application/json", f"mcp-{index}.json", kind, index
                )
        structured = result["structuredContent"]
        if structured is not None and len(encoded(structured).encode()) > 16_000:
            await save(
                encoded(structured).encode(),
                "application/json",
                "mcp-structured.json",
                "structured",
                -1,
            )
            structured = None
        return {
            "content": content,
            "structuredContent": structured,
            "artifactRefs": references,
            "outputExternalized": True,
        }
