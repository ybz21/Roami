"""Project-scoped admission for an external daily trigger."""

import json

from roami_agent.conversation.conversation_identity import conversation_identity
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.transcript_repository import history


def assert_project_main(db, owner, cid, project_id):
    identity = conversation_identity(db, owner, cid)
    if identity["kind"] != "project_main" or identity.get("projectId") != project_id:
        raise DomainError("PROJECT_MAIN_IDENTITY_MISMATCH", 409)


def assert_main_idle(db, conversation, *, ignore_turn_id=None):
    branch = conversation["active_branch_id"]
    if row(
        db,
        "SELECT id FROM turns WHERE branch_id=? AND state IN ('queued','running') "
        "AND (? IS NULL OR id!=?) LIMIT 1",
        (branch, ignore_turn_id, ignore_turn_id),
    ):
        raise DomainError("MAIN_BUSY", 409)
    messages = history(db, branch)
    if (
        messages
        and messages[-1]["role"] == "assistant"
        and json.loads(messages[-1]["content_json"]).get("question")
    ):
        raise DomainError("MAIN_WAITING_USER", 409)
