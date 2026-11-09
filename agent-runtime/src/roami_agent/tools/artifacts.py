"""Owner-scoped, bounded text evidence retrieval for Workers."""

import base64

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.storage.database import row
from roami_agent.storage.file_lines import read_line_page


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
        if (
            binding.get("fileReadLines")
            and args.get("offset", 1) != 0
            and args.get("limit", 2000) <= 2000
        ):
            reference, path = await artifacts.verified_path(owner, aid)

            def lines():
                with path.open("rb") as file:
                    return read_line_page(file, args.get("offset", 1), args.get("limit", 2000))

            page = await artifacts._io(lines)
            return {
                "artifact": reference,
                "textAvailable": page["encoding"] == "utf-8",
                "text": page["data"],
                **{key: value for key, value in page.items() if key != "data"},
                "paginationUnit": "lines",
                "hasMore": page["truncated"] or page["nextOffset"] is not None,
                "nextRead": {"offset": 0, "limit": 16000}
                if page["truncated"]
                else {"offset": page["nextOffset"], "limit": args.get("limit", 2000)}
                if page["nextOffset"] is not None
                else None,
            }
        offset, limit = args.get("offset", 0), args.get("limit", 8000)
        reference, excerpt = await artifacts.read_page(owner, aid, offset, limit)
        size = reference["sizeBytes"]
        try:
            text, encoding = excerpt.decode("utf-8"), "utf-8"
        except UnicodeDecodeError as exc:
            if exc.reason == "unexpected end of data" and exc.end == len(excerpt):
                if exc.start == 0:
                    raise DomainError("ARTIFACT_TEXT_LIMIT_TOO_SMALL", 400) from None
                excerpt = excerpt[: exc.start]
                text, encoding = excerpt.decode("utf-8"), "utf-8"
            else:
                text, encoding = base64.b64encode(excerpt).decode(), "base64"
        following = min(size, offset + len(excerpt))
        return {
            "artifact": reference,
            "textAvailable": encoding == "utf-8",
            "text": text,
            "encoding": encoding,
            "paginationUnit": "bytes",
            "nextRead": {"offset": following, "limit": 16000} if following < size else None,
            "offset": offset,
            "nextOffset": following,
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
