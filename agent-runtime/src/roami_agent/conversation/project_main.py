"""One durable coordinator identity per owner's project OKR."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row, rows
from roami_agent.storage.transcript_repository import owned


def project_team(db, owner, project_id, swarm_id):
    if not isinstance(swarm_id, str) or not swarm_id.startswith("sw-"):
        raise DomainError("PROJECT_OKR_TEAM_UNAVAILABLE", 409)
    swarm = row(db, "SELECT * FROM swarm_groups WHERE id=? AND owner_id=?", (swarm_id, owner))
    if not swarm or swarm["archived"]:
        raise DomainError("PROJECT_OKR_TEAM_UNAVAILABLE", 409)
    target = json.loads(swarm["target_json"])
    if target.get("kind") != "project" or target.get("projectId") != project_id:
        raise DomainError("PROJECT_OKR_TEAM_CONFLICT", 409)
    return swarm


def project_main(db, owner, project_id, title, create, *, swarm_id=None):
    current = row(
        db,
        "SELECT conversation_id FROM project_okr_mains WHERE owner_id=? AND project_id=?",
        (owner, project_id),
    )
    candidate = None
    if swarm_id and swarm_id.startswith("sw-"):
        swarm = project_team(db, owner, project_id, swarm_id)
        candidate = swarm["conversation_id"]
    if current:
        if candidate and candidate != current["conversation_id"]:
            raise DomainError("PROJECT_OKR_MAIN_CONFLICT", 409)
        candidate = current["conversation_id"]
    if not candidate:
        previous = row(
            db,
            "SELECT p.conversation_id FROM project_okr_conversations p JOIN conversations c ON c.id=p.conversation_id "
            "WHERE p.owner_id=? AND p.project_id=? AND c.deleted_ms IS NULL ORDER BY c.updated_ms DESC,c.id LIMIT 1",
            (owner, project_id),
        )
        candidate = previous["conversation_id"] if previous else None
    if candidate:
        conversation = owned(db, owner, candidate)
        if row(
            db,
            "SELECT 1 FROM main_conversations WHERE conversation_id=? UNION ALL "
            "SELECT 1 FROM native_sessions WHERE conversation_id=? UNION ALL "
            "SELECT 1 FROM swarm_member_instances WHERE conversation_id=? UNION ALL "
            "SELECT 1 FROM project_okr_conversations WHERE conversation_id=? AND (owner_id!=? OR project_id!=?)",
            (candidate, candidate, candidate, candidate, owner, project_id),
        ):
            raise DomainError("PROJECT_OKR_MAIN_CONFLICT", 409)
        for swarm in rows(
            db,
            "SELECT target_json FROM swarm_groups WHERE conversation_id=?",
            (candidate,),
        ):
            target = json.loads(swarm["target_json"])
            if target.get("kind") != "project" or target.get("projectId") != project_id:
                raise DomainError("PROJECT_OKR_MAIN_CONFLICT", 409)
    else:
        conversation = create(db, owner, title)
        candidate = conversation["id"]
    db.execute(
        "INSERT OR IGNORE INTO project_okr_conversations VALUES(?,?,?)",
        (candidate, owner, project_id),
    )
    db.execute(
        "INSERT OR IGNORE INTO project_okr_mains VALUES(?,?,?)", (owner, project_id, candidate)
    )
    return conversation
