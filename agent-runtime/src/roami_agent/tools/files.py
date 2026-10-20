"""Worker file tools bind every edit to the observed content hash."""

from roami_agent.protocol.tools import Tool, object_schema


def register_file_tools(registry, files):
    path = {"type": "string", "minLength": 1, "maxLength": 4096}
    digest = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
    registry.add(
        Tool(
            "file_read",
            "Read a prepared workspace file in bounded byte pages, returning its full content hash. Non-UTF-8 pages are base64. This is not an OS sandbox.",
            object_schema(
                {
                    "path": path,
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 16000},
                },
                ["path"],
            ),
            files.read,
        )
    )
    registry.add(
        Tool(
            "file_write",
            "Atomically publish UTF-8 content after checking expectedSha256 against the current file; null requires a new file. A changed source is a conflict: read it again before editing.",
            object_schema(
                {
                    "path": path,
                    "expectedSha256": {"anyOf": [digest, {"type": "null"}]},
                    "content": {"type": "string"},
                },
                ["path", "expectedSha256", "content"],
            ),
            files.write,
            effect="write",
        )
    )
    registry.add(
        Tool(
            "file_patch",
            "Replace exactly one literal text occurrence in a UTF-8 file after checking its observed hash. Reject ambiguous matches or changed files without writing.",
            object_schema(
                {
                    "path": path,
                    "expectedSha256": digest,
                    "oldText": {"type": "string", "minLength": 1},
                    "newText": {"type": "string"},
                },
                ["path", "expectedSha256", "oldText", "newText"],
            ),
            files.patch,
            effect="write",
        )
    )
