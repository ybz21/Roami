"""Reserved leader and exact member mentions preserve managed task routing."""

import re

from roami_agent.protocol.errors import DomainError


def recipient(spec, info):
    value = dict(spec)
    mention = re.match(r"^\s*@([^\s]+)(?:\s+|$)", value["text"])
    if not mention:
        return value
    name = mention[1]
    if name.casefold() in {"leader", "main"}:
        if value.get("workId"):
            raise DomainError("SWARM_RECIPIENT_CONFLICT", 409)
        return value
    member = next((work for work in info["work"] if work["member_name"] == name), None)
    if not member:
        raise DomainError("SWARM_MEMBER_TASK_REQUIRED", 409)
    if value.get("workId") and value["workId"] != member["id"]:
        raise DomainError("SWARM_RECIPIENT_CONFLICT", 409)
    value["workId"] = member["id"]
    if type(value.get("taskRevision")) is not int or value["taskRevision"] < 1:
        raise DomainError("TASK_REVISION_REQUIRED", 409)
    return value
