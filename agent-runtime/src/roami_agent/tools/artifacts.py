"""Owner-scoped, bounded text evidence retrieval for Workers."""

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.storage.database import row


def register_artifact_tools(registry, artifacts):
    async def read(args, binding):
        owner, aid = binding["owner"], args["id"]
        reference = await artifacts.get(owner, aid)
        if await artifacts.db.call(
            lambda db: row(
                db,
                "SELECT 1 FROM memory_tombstones WHERE owner_id=? AND source_fingerprint=?",
                (owner, reference["sha256"]),
            )
        ):
            raise DomainError("MEMORY_FORGOTTEN", 409)
        if not (
            reference["mimeType"].startswith("text/") or reference["mimeType"] == "application/json"
        ):
            await artifacts.verified_path(owner, aid)
            return {"artifact": reference, "textAvailable": False}
        offset, limit = args.get("offset", 0), args.get("limit", 8000)
        reference, excerpt = await artifacts.read_page(owner, aid, offset, limit)
        size = reference["sizeBytes"]
        return {
            "artifact": reference,
            "textAvailable": True,
            "text": excerpt.decode("utf-8", errors="replace"),
            "offset": offset,
            "nextOffset": min(size, offset + len(excerpt)),
            "hasMore": offset + len(excerpt) < size,
        }

    registry.add(
        Tool(
            "artifact_read",
            "Read a bounded UTF-8 excerpt of a stored artifact; binary returns metadata only.",
            object_schema(
                {
                    "id": {"type": "string", "minLength": 1, "maxLength": 200},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 16000},
                },
                ["id"],
            ),
            read,
        )
    )
