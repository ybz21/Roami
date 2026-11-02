"""Source-backed workspace hints; project configuration and existing bindings stay authoritative."""

from roami_agent.protocol.errors import DomainError


async def workspace_preference(memory, reference, binding, target):
    if not reference:
        return None
    record = await memory.get(binding["owner"], reference["memoryId"])
    if (
        record["kind"] != "preference"
        or record["revision"] != reference["revision"]
        or not reference["quote"].strip()
        or reference["quote"] not in record["body"]
        or record.get("conversation_id") not in {None, binding["conversation"]}
        or record.get("project_id") not in {None, target.get("projectId")}
        or record.get("task_id") is not None
        or target.get("kind") != "project"
        or target.get("workspaceId")
        or target.get("resourceOnly")
    ):
        raise DomainError("WORKFLOW_PREFERENCE_SOURCE_INVALID", 409)
    values = {"workspaceMode": "worktree"}
    for key in ("base", "remote"):
        value = reference.get(key)
        if value:
            if value not in reference["quote"] or value.startswith("-"):
                raise DomainError("WORKFLOW_PREFERENCE_SOURCE_INVALID", 409)
            values[key] = value
    return {
        "memoryId": record["id"],
        "revision": record["revision"],
        "quote": reference["quote"],
        "values": values,
    }
