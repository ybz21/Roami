"""Admission checks for work that can only run on an idle conversation."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.transcript_repository import history


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
