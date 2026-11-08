"""Current batch identity and original user delegation, independent of trigger names."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.swarm_delegations import current_delegation


def batch_context(db, owner, turn_id, *, lease_epoch=None):
    value = row(
        db,
        "SELECT b.*,t.conversation_id,t.branch_id,t.state,t.lease_epoch,c.owner_id FROM swarm_coordination_batches b "
        "JOIN turns t ON t.id=b.turn_id JOIN conversations c ON c.id=t.conversation_id "
        "WHERE b.turn_id=? AND c.owner_id=? AND c.deleted_ms IS NULL "
        "AND t.branch_id=c.active_branch_id AND t.state IN ('queued','running') "
        "AND t.trigger_kind='continuation' "
        "AND EXISTS(SELECT 1 FROM jobs j WHERE j.kind='turn.run' AND j.aggregate_id=t.id "
        "AND json_extract(j.payload_json,'$.coordinationBatchId')=b.id)",
        (turn_id, owner),
    )
    if (
        not value
        or lease_epoch is not None
        and (
            type(lease_epoch) is not int
            or value["state"] != "running"
            or value["lease_epoch"] != lease_epoch
        )
    ):
        raise DomainError("SWARM_COORDINATION_NOT_CURRENT", 409)
    delegation = current_delegation(db, owner, value["swarm_id"], value["delegation_id"])
    if value["state"] == "queued":
        job = row(
            db,
            "SELECT json_extract(payload_json,'$.dailySlot') AS slot FROM jobs "
            "WHERE kind='turn.run' AND aggregate_id=?",
            (turn_id,),
        )
        if job and job["slot"]:
            try:
                slot = json.loads(job["slot"])
                current_date = datetime.now(ZoneInfo(slot["timezone"])).date().isoformat()
                valid = slot["delegationId"] == delegation["id"] and slot["date"] == current_date
            except (ValueError, TypeError, KeyError, ZoneInfoNotFoundError):
                valid = False
            if not valid:
                raise DomainError("SWARM_DAILY_DATE_EXPIRED", 409)
    return {**value, "delegation": delegation}


def for_turn(db, turn):
    batch = row(db, "SELECT id FROM swarm_coordination_batches WHERE turn_id=?", (turn["id"],))
    job = row(
        db,
        "SELECT json_extract(payload_json,'$.coordinationBatchId') AS batch_id FROM jobs "
        "WHERE kind='turn.run' AND aggregate_id=?",
        (turn["id"],),
    )
    if not batch and not (job and job["batch_id"]):
        return None
    if type(turn.get("lease_epoch")) is not int:
        raise DomainError("SWARM_COORDINATION_NOT_CURRENT", 409)
    return batch_context(db, turn["owner_id"], turn["id"], lease_epoch=turn["lease_epoch"])
