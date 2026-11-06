"""Bind collaboration to the existing project's canonical Main, never its name."""

import json
import sqlite3

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row, rows


def project_scope(db, owner, cid, target):
    if target.get("kind") != "project":
        return None
    pid = target.get("projectId")
    binding = row(
        db,
        "SELECT project_id FROM project_okr_conversations WHERE owner_id=? AND conversation_id=?",
        (owner, cid),
    )
    if binding and binding["project_id"] != pid:
        raise DomainError("PROJECT_OKR_TEAM_CONFLICT", 409)
    current = row(
        db,
        "SELECT p.project_id FROM project_okr_mains p JOIN project_okr_conversations b "
        "ON b.conversation_id=p.conversation_id AND b.owner_id=p.owner_id AND b.project_id=p.project_id "
        "JOIN conversations c ON c.id=p.conversation_id AND c.owner_id=p.owner_id AND c.deleted_ms IS NULL "
        "WHERE p.owner_id=? AND p.project_id=? AND p.conversation_id=? "
        "AND NOT EXISTS(SELECT 1 FROM main_conversations h WHERE h.conversation_id=p.conversation_id) "
        "AND NOT EXISTS(SELECT 1 FROM native_sessions n WHERE n.conversation_id=p.conversation_id) "
        "AND NOT EXISTS(SELECT 1 FROM task_attempts a JOIN branches b ON b.id=a.native_branch_id WHERE b.conversation_id=p.conversation_id) "
        "AND NOT EXISTS(SELECT 1 FROM swarm_member_instances i WHERE i.conversation_id=p.conversation_id)",
        (owner, pid, cid),
    )
    if not current:
        raise DomainError("PROJECT_OKR_MAIN_CONFLICT", 409)
    return pid


def require_scope(value):
    if json.loads(value["target_json"]).get("kind") == "project" and not value["scope_project_id"]:
        raise DomainError("SWARM_PROJECT_SCOPE_REQUIRED", 409)


def receipt_swarm(value):
    try:
        receipt = json.loads(value)
        sid = receipt.get("swarmId", receipt.get("id"))
        return sid if isinstance(sid, str) and sid.startswith("sw-") else None
    except (ValueError, AttributeError):
        return None


def bind_project_scope(db, owner, pid, cid):
    project_scope(db, owner, cid, {"kind": "project", "projectId": pid})
    adopted = rows(
        db,
        "SELECT * FROM swarm_groups WHERE owner_id=? AND conversation_id=? "
        "AND scope_project_id IS NULL AND json_extract(target_json,'$.kind')='project' "
        "AND json_extract(target_json,'$.projectId')=?",
        (owner, cid, pid),
    )
    if any(
        row(
            db,
            "SELECT id FROM swarm_groups WHERE owner_id=? AND scope_project_id=? AND name=?",
            (owner, pid, value["name"]),
        )
        for value in adopted
    ):
        raise DomainError("PROJECT_OKR_TEAM_CONFLICT", 409)
    db.execute(
        "UPDATE swarm_groups SET scope_project_id=? WHERE owner_id=? AND conversation_id=? "
        "AND scope_project_id IS NULL AND json_extract(target_json,'$.kind')='project' "
        "AND json_extract(target_json,'$.projectId')=?",
        (pid, owner, cid, pid),
    )
    try:
        db.execute(
            "UPDATE swarm_commands SET scope_project_id=? WHERE owner_id=? AND scope_project_id='' "
            "AND EXISTS(SELECT 1 FROM swarm_groups g WHERE g.owner_id=? AND g.scope_project_id=? "
            "AND g.id=COALESCE(json_extract(CASE WHEN json_valid(receipt_json) THEN receipt_json ELSE '{}' END,'$.swarmId'),"
            "json_extract(CASE WHEN json_valid(receipt_json) THEN receipt_json ELSE '{}' END,'$.id')))",
            (pid, owner, owner, pid),
        )
    except sqlite3.IntegrityError as exc:
        raise DomainError("REQUEST_KEY_CONFLICT", 409) from exc
    from roami_agent.storage.swarm_repository import changed, enqueue

    for value in adopted:
        db.execute(
            "UPDATE swarm_work_items SET dispatch_error=NULL WHERE swarm_id=? AND task_id IS NULL "
            "AND dispatch_error='SWARM_PROJECT_SCOPE_REQUIRED'",
            (value["id"],),
        )
        changed(db, value, "swarm.scope_bound")
        enqueue(db, value["id"], "scope.bound:" + value["id"])


def legacy_receipt_in_scope(db, owner, pid, receipt):
    sid = receipt_swarm(receipt["receipt_json"])
    if not sid:
        raise DomainError("REQUEST_KEY_CONFLICT", 409)
    source = row(db, "SELECT target_json FROM swarm_groups WHERE owner_id=? AND id=?", (owner, sid))
    if not source:
        raise DomainError("REQUEST_KEY_CONFLICT", 409)
    target = json.loads(source["target_json"])
    return target.get("kind") == "project" and target.get("projectId") == pid
