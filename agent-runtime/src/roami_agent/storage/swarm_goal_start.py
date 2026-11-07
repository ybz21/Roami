"""Start the original Main once after a real current-user goal delegation."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row
from roami_agent.storage.swarm_coordination import enqueue
from roami_agent.storage.swarm_delegations import current_delegation

KIND = "swarm.goal.start"


def queue_start(db, swarm_id, delegation_id):
    key = "swarm.goal.start:" + delegation_id
    db.execute(
        "INSERT OR IGNORE INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) "
        "VALUES(?,?,?,?,?,'queued',?)",
        (
            identity(),
            KIND,
            swarm_id,
            key,
            encoded({"swarmId": swarm_id, "delegationId": delegation_id}),
            now_ms(),
        ),
    )
    return row(db, "SELECT id FROM jobs WHERE dedupe_key=?", (key,))["id"]


def advance(db, job_id):
    job = row(db, "SELECT * FROM jobs WHERE id=? AND kind=?", (job_id, KIND))
    if not job or job["state"] not in {"queued", "running", "done"}:
        raise DomainError("SWARM_GOAL_START_NOT_CURRENT", 409)
    payload = json.loads(job["payload_json"])
    if job["state"] == "done":
        return payload

    def finish(**outcome):
        result = {**payload, **outcome}
        db.execute(
            "UPDATE jobs SET state='done',payload_json=? WHERE id=?", (encoded(result), job_id)
        )
        return result

    team = row(db, "SELECT * FROM swarm_groups WHERE id=?", (payload["swarmId"],))
    if not team or team["archived"]:
        return finish(skipped="team_unavailable")
    try:
        delegation = current_delegation(db, team["owner_id"], team["id"], payload["delegationId"])
        source = row(
            db,
            "SELECT t.* FROM turns t JOIN messages m ON m.turn_id=t.id WHERE m.id=?",
            (delegation["source_message_id"],),
        )
        if not source or row(
            db,
            "SELECT id FROM jobs WHERE kind='control.stop' AND json_extract(payload_json,'$.turnId')=?",
            (source["id"],),
        ):
            return finish(skipped="source_stopped")
        if source["state"] in {"queued", "running"}:
            raise DomainError("MAIN_BUSY", 409)
        existing = row(
            db,
            "SELECT b.id AS batchId,b.turn_id AS turnId FROM swarm_coordination_batches b "
            "JOIN jobs j ON j.aggregate_id=b.turn_id AND j.kind='turn.run' "
            "WHERE b.delegation_id=? AND json_extract(j.payload_json,'$.initialGoalId')=?",
            (delegation["id"], delegation["id"]),
        )
        if existing:
            return finish(**existing)
        batch = enqueue(db, team["owner_id"], team["id"], initial_goal_id=delegation["id"])
    except DomainError as exc:
        if exc.code not in {"MAIN_BUSY", "MAIN_WAITING_USER", "SWARM_COORDINATION_PAUSED"}:
            return finish(skipped=exc.code)
        db.execute(
            "UPDATE jobs SET state='queued',available_ms=? WHERE id=?", (now_ms() + 1000, job_id)
        )
        return {**payload, "waiting": exc.code}
    return finish(**batch)
