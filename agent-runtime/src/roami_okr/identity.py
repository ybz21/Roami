"""Resolve the project Main identity without creating or rebinding a conversation."""

from roami_agent.conversation.conversation_identity import conversation_identity
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row, rows


def project_conversation_identity(db, owner, cid):
    project = row(
        db,
        "SELECT project_id FROM project_okr_mains WHERE owner_id=? AND conversation_id=?",
        (owner, cid),
    )
    result = conversation_identity(db, owner, cid, reserved=project is not None)
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


def home_exclusions(db, owner):
    return [
        row["conversation_id"]
        for row in rows(
            db,
            "SELECT p.conversation_id FROM project_okr_conversations p "
            "JOIN conversations c ON c.id=p.conversation_id WHERE c.owner_id=?",
            (owner,),
        )
    ]
