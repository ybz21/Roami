"""Read coordinator and member identity without creating or rebinding conversations."""

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row, rows
from roami_agent.storage.transcript_repository import owned


def conversation_identity(db, owner, cid):
    conversation = owned(db, owner, cid)
    result = {
        "conversationId": cid,
        "activeBranchId": conversation["active_branch_id"],
        "kind": "conversation",
    }
    home = row(
        db,
        "SELECT conversation_id FROM main_conversations WHERE owner_id=? AND conversation_id=?",
        (owner, cid),
    )
    project = row(
        db,
        "SELECT project_id FROM project_okr_mains WHERE owner_id=? AND conversation_id=?",
        (owner, cid),
    )
    native = row(
        db,
        "SELECT id,task_id FROM native_sessions WHERE owner_id=? AND conversation_id=?",
        (owner, cid),
    )
    instance = row(
        db,
        "SELECT i.*,m.swarm_id FROM swarm_member_instances i JOIN swarm_members m ON m.id=i.member_id WHERE i.owner_id=? AND i.conversation_id=?",
        (owner, cid),
    )
    worker = row(
        db,
        "SELECT DISTINCT t.id FROM task_attempts a JOIN tasks t ON t.id=a.task_id JOIN branches b ON b.id=a.native_branch_id WHERE b.conversation_id=? AND t.owner_id=? LIMIT 1",
        (cid, owner),
    )
    if project and (home or native or worker or instance):
        raise DomainError("CONVERSATION_IDENTITY_CONFLICT", 409)
    if native or worker or instance:
        if home:
            raise DomainError("CONVERSATION_IDENTITY_CONFLICT", 409)
        if instance and native and native["task_id"] != instance["task_id"]:
            raise DomainError("CONVERSATION_IDENTITY_CONFLICT", 409)
        if native:
            from roami_agent.storage.native_sessions import NativeSessions

            NativeSessions._get(db, owner, native["id"])
        return {
            **result,
            "kind": "member",
            "taskId": native["task_id"]
            if native
            else worker["id"]
            if worker
            else instance["task_id"],
            **(
                {
                    "memberId": instance["member_id"],
                    "instanceId": instance["id"],
                    "swarmId": instance["swarm_id"],
                }
                if instance
                else {}
            ),
            **({"nativeSessionId": native["id"]} if native else {}),
        }
    if home:
        return {**result, "kind": "home_main"}
    if project:
        binding = row(
            db,
            "SELECT project_id FROM project_okr_conversations WHERE owner_id=? AND conversation_id=?",
            (owner, cid),
        )
        groups = rows(
            db,
            "SELECT json_extract(target_json,'$.projectId') AS project_id FROM swarm_groups WHERE owner_id=? AND conversation_id=?",
            (owner, cid),
        )
        if (
            not binding
            or binding["project_id"] != project["project_id"]
            or any(group["project_id"] != project["project_id"] for group in groups)
        ):
            raise DomainError("CONVERSATION_IDENTITY_CONFLICT", 409)
        return {**result, "kind": "project_main", "projectId": project["project_id"]}
    return result
