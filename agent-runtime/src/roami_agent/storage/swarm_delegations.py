"""A stored human goal is authority; a member message or trigger label is not."""

import hashlib
import json

from roami_agent.conversation.okr_message_context import human_text
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row
from roami_agent.storage.request_quotes import source_quote
from roami_agent.storage.swarm_repository import group
from roami_agent.storage.swarm_scopes import require_scope


def source_digest(content):
    return hashlib.sha256(encoded(json.loads(content)).encode()).hexdigest()


def visible_source(db, branch_id, source):
    through = None
    for _ in range(17):
        branch = row(db, "SELECT * FROM branches WHERE id=?", (branch_id,))
        if not branch:
            return False
        if branch_id == source["branch_id"]:
            return source["seq"] <= (branch["head_seq"] if through is None else through)
        if not branch["parent_branch_id"]:
            return False
        cut = row(db, "SELECT seq FROM messages WHERE id=?", (branch["fork_message_id"],))
        if not cut:
            return False
        branch_id, through = branch["parent_branch_id"], cut["seq"]
    return False


def user_source(db, owner, conversation_id, message_id):
    return row(
        db,
        "SELECT m.*,native_content(m.content_json) AS body FROM messages m "
        "JOIN turns t ON t.id=m.turn_id AND t.conversation_id=m.conversation_id "
        "JOIN conversations c ON c.id=m.conversation_id "
        "WHERE m.id=? AND m.conversation_id=? AND c.owner_id=? AND t.trigger_kind='user' "
        "AND m.role='user' AND m.deleted_ms IS NULL AND m.status!='deleted' AND c.deleted_ms IS NULL "
        "AND json_type(native_content(m.content_json),'$.scheduled') IS NULL "
        "AND NOT EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=c.owner_id AND o.message_id=m.id)",
        (message_id, conversation_id, owner),
    )


def source_messages(db, turn, source):
    manifest = row(
        db,
        "SELECT parts_json FROM prompt_manifests WHERE turn_id=? ORDER BY attempt_no DESC LIMIT 1",
        (turn["id"],),
    )
    candidates = json.loads(manifest["parts_json"]).get("sourceMessageIds", []) if manifest else []
    result = [source["id"]]
    for message_id in candidates:
        if not isinstance(message_id, str) or message_id in result:
            continue
        actual = user_source(db, turn["owner_id"], turn["conversation_id"], message_id)
        if actual and visible_source(db, turn["branch_id"], actual):
            result.append(message_id)
    return result


def current_delegation(db, owner, swarm_id, delegation_id=None, *, allow_paused=False):
    team = group(db, owner, swarm_id)
    require_scope(team)
    if team["scope_project_id"] is None:
        raise DomainError("SWARM_PROJECT_REQUIRED", 409)
    if team["archived"] or (team["paused"] and not allow_paused):
        raise DomainError("SWARM_COORDINATION_PAUSED", 409)
    value = row(
        db,
        "SELECT * FROM swarm_goal_delegations WHERE swarm_id=? AND revoked_ms IS NULL "
        "AND (? IS NULL OR id=?) ORDER BY revision DESC LIMIT 1",
        (swarm_id, delegation_id, delegation_id),
    )
    if not value:
        raise DomainError("SWARM_DELEGATION_REQUIRED", 409)
    conversation = row(
        db, "SELECT active_branch_id FROM conversations WHERE id=?", (team["conversation_id"],)
    )
    source = user_source(db, owner, team["conversation_id"], value["source_message_id"])
    if not source or source_digest(source["body"]) != value["source_sha256"]:
        raise DomainError("SWARM_DELEGATION_SOURCE_FORGOTTEN", 409)
    if source_quote(human_text(json.loads(source["body"])), value["source_quote"]) is None:
        raise DomainError("SWARM_DELEGATION_SOURCE_REQUIRED", 409)
    for message_id in json.loads(value["source_messages_json"]):
        actual = user_source(db, owner, team["conversation_id"], message_id)
        if not actual or not visible_source(db, conversation["active_branch_id"], actual):
            raise DomainError("SWARM_DELEGATION_SOURCE_FORGOTTEN", 409)
    return {
        **value,
        "projectId": team["scope_project_id"],
        "mainConversationId": team["conversation_id"],
        "source": source,
    }
