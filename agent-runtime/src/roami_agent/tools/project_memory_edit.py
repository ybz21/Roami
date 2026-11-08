"""Small, revision-checked edits to the bound project's canonical team memory."""

import hashlib
import re

from roami_agent.conversation.project_okr import bound_project, operation
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.protocol.tools import Tool, object_schema


def memory_edit_fields():
    return {
        "expectedSha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "edits": {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "items": object_schema(
                {
                    "oldText": {"type": "string", "minLength": 1, "maxLength": 65536},
                    "newText": {"type": "string", "maxLength": 65536},
                },
                ["oldText", "newText"],
            ),
        },
    }


def memory_edit_payload(args, binding):
    edits = args["edits"]
    if any(item["oldText"] == item["newText"] for item in edits):
        raise DomainError("INVALID_MEMORY_EDIT")
    try:
        size = sum(len(item[key].encode()) for item in edits for key in ("oldText", "newText"))
        digest = hashlib.sha256(encoded(edits).encode()).hexdigest()
    except UnicodeError:
        raise DomainError("INVALID_MEMORY_EDIT") from None
    if size > 65536:
        raise DomainError("INVALID_MEMORY_EDIT")
    key = binding.get("coordinationMemoryEditKey")
    if key is None:
        turn = binding.get("turnId")
        if not isinstance(turn, str) or not turn or len(turn) > 100:
            raise DomainError("MEMORY_EDIT_TURN_REQUIRED", 403)
        key = "memory-edit:" + turn + ":" + digest
    return {
        "mode": "edit",
        "operationKey": key,
        "expectedSha256": args["expectedSha256"],
        "edits": edits,
    }


def memory_edit_receipt(workspace, project_id, operation_key):
    if not isinstance(workspace, dict) or workspace.get("projectId") != project_id:
        raise DomainError("PROJECT_MEMORY_EDIT_RECEIPT_UNAVAILABLE", 503)
    files = workspace.get("projectFiles")
    if not isinstance(files, dict):
        raise DomainError("PROJECT_MEMORY_EDIT_RECEIPT_UNAVAILABLE", 503)
    receipt = files.get("operationReceipt")
    digest = files.get("teamMemorySha256")
    if (
        files.get("memoryEditsSupported") is not True
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or not isinstance(receipt, dict)
        or receipt.get("kind") != "memory_edit"
        or receipt.get("key") != operation_key
        or any(
            not isinstance(receipt.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", receipt[key])
            for key in ("requestSha256", "previousSha256", "resultSha256")
        )
        or not isinstance(receipt.get("recordedAt"), str)
        or not receipt["recordedAt"]
    ):
        raise DomainError("PROJECT_MEMORY_EDIT_RECEIPT_UNAVAILABLE", 503)
    return {
        "available": True,
        "source": ".roami/okr/memory/team.md",
        "sha256": digest,
        "operationReceipt": receipt,
    }


def register_project_memory_edit(registry, database, settings):
    async def edit(args, binding):
        project_id = await bound_project(database, binding)
        workspace = await operation(settings, project_id, "show")
        if (
            not workspace
            or (workspace.get("projectFiles") or {}).get("memoryEditsSupported") is not True
        ):
            raise DomainError("PROJECT_MEMORY_EDIT_UNAVAILABLE", 409)
        payload = memory_edit_payload(args, binding)
        result = await operation(settings, project_id, "memory", payload)
        return memory_edit_receipt(result, project_id, payload["operationKey"])

    registry.add(
        Tool(
            "project_okr_memory_edit",
            "Edit exact unique fragments in this project's team memory using the last read "
            "expectedSha256. Read project_okr_context first. Submit oldText/newText edits, "
            "not the full document; fragments must not overlap. The host fixes project and "
            "retry identity, retains prior bytes and returns a compact receipt. Append adds "
            "new knowledge; it does not change an existing rule. Reread actual memory to "
            "verify the result before claiming the old rule changed. No paths or secrets.",
            object_schema(memory_edit_fields(), ["expectedSha256", "edits"]),
            edit,
            main=True,
            effect="write",
        )
    )
