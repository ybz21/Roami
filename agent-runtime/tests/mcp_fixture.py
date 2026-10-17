"""Real stdio MCP fixture; state files make disconnect and catalog changes observable."""

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

root = Path(sys.argv[1])
server = Server("roami-mcp-fixture")


@server.list_tools()
async def tools():
    state = json.loads(await asyncio.to_thread((root / "state.json").read_text))
    schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    }
    if state.get("changed"):
        schema["properties"]["text"]["maxLength"] = 10
    return [
        types.Tool(name=name, description="Fixture " + name, inputSchema=schema)
        for name in ["echo", "slow", "large", "failure", "changed"]
        if name not in state.get("removed", [])
    ]


@server.call_tool(validate_input=False)
async def call(name, arguments):
    await asyncio.to_thread((root / ("called-" + name)).write_text, str(os.getpid()))
    token = server.request_context.meta.progressToken if server.request_context.meta else None
    if token is not None:
        await server.request_context.session.send_progress_notification(
            token, 1, 2, "sensitive progress detail"
        )
    if name == "slow":
        await asyncio.sleep(120)
    if name == "changed":
        await asyncio.to_thread((root / "state.json").write_text, '{"changed":true}')
        await server.request_context.session.send_tool_list_changed()
    if name == "failure":
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="secret fixture details")], isError=True
        )
    body = {
        "text": arguments["text"],
        "credentialConfigured": os.environ.get("MCP_AUTH_TOKEN") == "fixture-token",
        "modelKeyInherited": "ROAMI_AGENT_API_KEY" in os.environ,
    }
    return types.CallToolResult(
        content=[types.TextContent(type="text", text="x" * 65_000 if name == "large" else "ok")],
        structuredContent=body,
    )


async def main():
    await asyncio.to_thread((root / "pid").write_text, str(os.getpid()))
    async with stdio_server() as streams:
        await server.run(*streams, server.create_initialization_options())


asyncio.run(main())
