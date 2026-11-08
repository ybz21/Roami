"""Internal date-slot queue for a validated schedule on an existing user goal."""

import hashlib
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row
from roami_agent.storage.swarm_coordination import enqueue
from roami_agent.storage.swarm_delegations import current_delegation

KIND = "swarm.goal.daily"


def date_slot(delegation_id, *, timezone, slot, clock=None):
    if not isinstance(slot, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", slot):
        raise DomainError("INVALID_SWARM_DAILY_SLOT")
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise DomainError("INVALID_SWARM_DAILY_TIMEZONE") from None
    stamp = clock or datetime.now(zone)
    if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
        raise DomainError("INVALID_SWARM_DAILY_CLOCK")
    return {
        "delegationId": delegation_id,
        "timezone": timezone,
        "date": stamp.astimezone(zone).date().isoformat(),
        "slot": slot,
    }


def queue(db, owner, swarm_id, delegation_id, *, timezone, slot, clock=None, expected_date=None):
    goal = current_delegation(db, owner, swarm_id, delegation_id, allow_paused=True)
    marker = date_slot(goal["id"], timezone=timezone, slot=slot, clock=clock)
    if expected_date is not None and marker["date"] != expected_date:
        raise DomainError("SWARM_DAILY_DATE_EXPIRED", 409)
    key = KIND + ":" + hashlib.sha256(encoded(marker).encode()).hexdigest()
    existing = row(db, "SELECT id,payload_json FROM jobs WHERE dedupe_key=?", (key,))
    if existing:
        return {"jobId": existing["id"], **json.loads(existing["payload_json"])}
    payload = {"swarmId": swarm_id, "ownerId": owner, "dailySlot": marker}
    job_id = identity()
    db.execute(
        "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) "
        "VALUES(?,?,?,?,?,'queued',?)",
        (job_id, KIND, swarm_id, key, encoded(payload), now_ms()),
    )
    return {"jobId": job_id, **payload}


def advance(db, job_id, *, clock=None):
    job = row(db, "SELECT * FROM jobs WHERE id=? AND kind=?", (job_id, KIND))
    if not job or job["state"] not in {"queued", "running", "done"}:
        raise DomainError("SWARM_DAILY_NOT_CURRENT", 409)
    payload = json.loads(job["payload_json"])
    if job["state"] == "done":
        return payload

    def finish(**outcome):
        result = {**payload, **outcome}
        db.execute(
            "UPDATE jobs SET state='done',payload_json=? WHERE id=?", (encoded(result), job_id)
        )
        return result

    team = row(
        db,
        "SELECT archived FROM swarm_groups WHERE id=? AND owner_id=?",
        (payload["swarmId"], payload["ownerId"]),
    )
    if not team or team["archived"]:
        return finish(skipped="team_unavailable")
    try:
        marker = payload["dailySlot"]
        current_delegation(db, payload["ownerId"], payload["swarmId"], marker["delegationId"])
        zone = ZoneInfo(marker["timezone"])
        today = (clock or datetime.now(zone)).astimezone(zone).date().isoformat()
        if marker["date"] != today:
            return finish(
                skipped="date_slot_expired" if marker["date"] < today else "date_slot_future"
            )
        existing = row(
            db,
            "SELECT b.id AS batchId,b.turn_id AS turnId FROM swarm_coordination_batches b "
            "JOIN jobs j ON j.aggregate_id=b.turn_id AND j.kind='turn.run' "
            "WHERE b.delegation_id=? AND json_extract(j.payload_json,'$.dailySlot')=json(?)",
            (marker["delegationId"], encoded(marker)),
        )
        if existing:
            return finish(**existing)
        batch = enqueue(db, payload["ownerId"], payload["swarmId"], daily_slot=marker)
    except DomainError as exc:
        if exc.code not in {"MAIN_BUSY", "MAIN_WAITING_USER", "SWARM_COORDINATION_PAUSED"}:
            return finish(skipped=exc.code)
        db.execute(
            "UPDATE jobs SET state='queued',available_ms=? WHERE id=?", (now_ms() + 1000, job_id)
        )
        return {**payload, "waiting": exc.code}
    return finish(**batch)
