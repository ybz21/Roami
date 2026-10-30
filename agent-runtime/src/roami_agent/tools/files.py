"""Worker file tools bind every edit to the observed content hash."""

from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.tools.workspace_presentations import WorkspacePresentationReads


def register_file_tools(registry, files, *, images=None):
    presentations = WorkspacePresentationReads(files, images.read if images else files.read)
    path = {"type": "string", "minLength": 1, "maxLength": 4096}
    digest = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
    registry.add(
        Tool(
            "file_read",
            "Read one file in bounded byte pages with its original content hash. Use view=document for PPTX text objects, groups and editor palette before editing. Document view pages describe the inspection, not the source bytes. Raw non-UTF-8 pages are base64. Main: delegate repository/code work when only a directory is known; do not guess filenames.",
            object_schema(
                {
                    "path": path,
                    "view": {"enum": ["raw", "document"]},
                    "offset": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 16000},
                },
                ["path"],
            ),
            presentations.read,
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
