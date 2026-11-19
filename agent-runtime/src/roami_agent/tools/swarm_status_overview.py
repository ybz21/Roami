"""Keep current coordination identities visible beside an externalized history."""

from roami_agent.protocol.serialization import encoded


def fields(value, names):
    return {name: value[name] for name in names if name in value}


def page(items, budget):
    kept = []
    used = 0
    for item in items:
        size = len(encoded(item).encode())
        if used + size > budget:
            break
        kept.append(item)
        used += size
    return {"items": kept, "total": len(items), "hasMore": len(kept) < len(items)}


def overview(value, member_ids=None):
    selected = set(member_ids) if member_ids is not None else None
    members = []
    for member in value.get("members", []):
        if selected is not None and member.get("id") not in selected:
            continue
        item = fields(
            member,
            (
                "id",
                "name",
                "executor",
                "model",
                "execution_generation",
                "workId",
                "taskId",
                "taskRevision",
                "state",
            ),
        )
        if member.get("provider"):
            item["provider"] = fields(
                member["provider"], ("generation", "sessionId", "executor", "model")
            )
        members.append(item)
    work = []
    for current in value.get("work", []):
        if selected is not None and current.get("memberId") not in selected:
            continue
        item = fields(current, ("id", "memberId", "task_id", "revision", "state", "executor"))
        item["attempt"] = (
            fields(current["attempt"], ("runId", "state", "sessionId", "finishedMs"))
            if current.get("attempt")
            else None
        )
        work.append(item)
    return {
        "selection": "admitted_goal_members" if selected is not None else "registered_members",
        "members": page(members, 6000),
        "work": page(work, 8000),
        "details": {
            "tasks": "task_status with taskId and includeResult=true",
            "pendingMessages": "swarm_inbox_read with swarmId",
            "memberHistory": "swarm_member with swarmId and memberId",
            "fullSnapshot": "artifactRefs contains the complete snapshot, including history and memory",
        },
    }
