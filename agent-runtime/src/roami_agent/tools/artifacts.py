"""Owner-scoped, bounded text evidence retrieval for Workers."""

from roami_agent.protocol.tools import Tool, object_schema


def register_artifact_tools(registry, artifacts):
    async def read(args, binding):
        owner, aid = binding["owner"], args["id"]
        reference = await artifacts.get(owner, aid)
        if not (
            reference["mimeType"].startswith("text/") or reference["mimeType"] == "application/json"
        ):
            await artifacts.verified_path(owner, aid)
            return {"artifact": reference, "textAvailable": False}
        reference, body = await artifacts.read(owner, aid)
        offset, limit = args.get("offset", 0), args.get("limit", 8000)
        excerpt = body[offset : offset + limit]
        return {
            "artifact": reference,
            "textAvailable": True,
            "text": excerpt.decode("utf-8", errors="replace"),
            "offset": offset,
            "nextOffset": min(len(body), offset + len(excerpt)),
            "hasMore": offset + len(excerpt) < len(body),
        }

    registry.add(
        Tool(
            "artifact_read",
            "Read a bounded UTF-8 excerpt of a stored artifact; binary returns metadata only.",
            object_schema(
                {
                    "id": {"type": "string", "minLength": 1, "maxLength": 200},
                    "offset": {"type": "integer", "minimum": 0, "maximum": 536870912},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 16000},
                },
                ["id"],
            ),
            read,
        )
    )
