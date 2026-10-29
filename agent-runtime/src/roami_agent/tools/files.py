"""Worker file tools bind every edit to the observed content hash."""

from roami_agent.protocol.tools import Tool, object_schema


def register_file_tools(registry, files, *, images=None):
    path = {"type": "string", "minLength": 1, "maxLength": 4096}
    digest = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
    registry.add(
        Tool(
            "file_read",
            "Read one file, not a directory, in bounded byte pages, returning its full content hash. Main: if only a directory is known, delegate repository/code work to a Worker there; do not guess filenames. Non-UTF-8 pages are base64. This is not an OS sandbox.",
            object_schema(
                {
                    "path": path,
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 16000},
                },
                ["path"],
            ),
            images.read if images else files.read,
        )
    )
    registry.add(
        Tool(
            "file_write",
            "Atomically publish UTF-8 content. To create a new file prefer expectedSha256 as actual JSON null (unquoted). For an existing file use the exact sha256 returned by file_read. A changed source is a conflict: read it again before editing.",
            object_schema(
                {
                    "path": path,
                    "expectedSha256": {
                        "description": 'New file: JSON null, without quotes. The literal string "null" also means exclusive creation only. Existing file: exact sha256 from read. Example: {"path":"answer.txt","expectedSha256":null,"content":"Answer"}. Never guess a hash.',
                        "anyOf": [
                            digest,
                            {"type": "null"},
                            {"type": "string", "enum": ["null"]},
                        ],
                    },
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
