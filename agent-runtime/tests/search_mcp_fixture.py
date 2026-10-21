"""A public-search-shaped MCP server with an unclassified write operation."""

import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

server = FastMCP("search-fixture")
root = Path(sys.argv[1])


@server.tool()
def search(query: str) -> dict:
    (root / "searched").write_text(query)
    if query == "no-sources":
        return {"text": "No source was retrieved"}
    return {
        "results": [{"url": "https://source.example/news?a=1&b=2", "text": "Fixture market news"}]
    }


@server.tool()
def publish(text: str) -> str:
    (root / "published").write_text(text)
    return "Published"


server.run()
