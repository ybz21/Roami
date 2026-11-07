"""Deliver current selected-member questions to their original delegated Main."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row
from roami_agent.storage.swarm_coordination import enqueue
from roami_agent.storage.swarm_delegations import current_delegation

KIND = "swarm.inbox.wakeup"


def _source(db, inbox_id, delegation):
    return row(
        db,
        "SELECT i.id FROM swarm_inbox i JOIN swarm_post_routes r ON r.post_id=i.post_id "
        "JOIN swarm_posts p ON p.id=i.post_id JOIN swarm_members m ON m.id=r.author_member_id "
        "JOIN swarm_work_items w ON w.id=m.current_work_id AND w.task_id=p.task_id "
        "JOIN tasks t ON t.id=p.task_id "
        "WHERE i.id=? AND i.main_conversation_id=? AND i.handled_post_id IS NULL "
        "AND r.swarm_id=? AND r.author_kind='member' "
        "AND p.swarm_id=r.swarm_id AND m.swarm_id=r.swarm_id AND w.swarm_id=r.swarm_id "
        "AND r.author_member_id IN (SELECT value FROM json_each(?)) "
        "AND r.source_task_revision=t.revision "
        "AND r.source_run_id=(SELECT a.id FROM task_attempts a WHERE a.task_id=t.id "
        "AND a.task_revision=t.revision ORDER BY a.attempt_no DESC LIMIT 1)",
        (
            inbox_id,
            delegation["mainConversationId"],
            delegation["swarm_id"],
            delegation["member_ids_json"],
        ),
    )


def queue_post(db, team, post_id):
    inbox = row(
        db,
        "SELECT id FROM swarm_inbox WHERE post_id=? AND main_conversation_id=?",
        (post_id, team["conversation_id"]),
    )
    if not inbox:
        return None
    try:
        delegation = current_delegation(db, team["owner_id"], team["id"], allow_paused=True)
    except DomainError:
        return None
    if not _source(db, inbox["id"], delegation):
        return None
    key = "swarm.inbox.wakeup:" + delegation["id"] + ":" + str(inbox["id"])
    db.execute(
        "INSERT OR IGNORE INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) "
        "VALUES(?,?,?,?,?,'queued',?)",
        (
            identity(),
            KIND,
            team["id"],
            key,
            encoded(
                {"swarmId": team["id"], "delegationId": delegation["id"], "inboxId": inbox["id"]}
            ),
            now_ms(),
        ),
    )
    return row(db, "SELECT id FROM jobs WHERE dedupe_key=?", (key,))["id"]


def advance(db, job_id):
    job = row(db, "SELECT * FROM jobs WHERE id=? AND kind=?", (job_id, KIND))
    if not job or job["state"] not in {"queued", "running", "done"}:
        raise DomainError("SWARM_INBOX_WAKEUP_NOT_CURRENT", 409)
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
        delegation = current_delegation(
            db, team["owner_id"], team["id"], payload["delegationId"], allow_paused=True
        )
    except DomainError as exc:
        return finish(skipped=exc.code)
    if not _source(db, payload["inboxId"], delegation):
        return finish(skipped="source_not_current")
    frozen = row(
        db,
        "SELECT b.id AS batchId,b.turn_id AS turnId FROM swarm_coordination_inputs i "
        "JOIN swarm_coordination_batches b ON b.id=i.batch_id WHERE i.inbox_id=?",
        (payload["inboxId"],),
    )
    if frozen:
        return finish(**frozen, handled=False)
    try:
        batch = enqueue(db, team["owner_id"], team["id"])
    except DomainError as exc:
        if exc.code not in {"MAIN_BUSY", "MAIN_WAITING_USER", "SWARM_COORDINATION_PAUSED"}:
            return finish(skipped=exc.code)
        waiting = exc.code
    else:
        included = row(
            db,
            "SELECT batch_id FROM swarm_coordination_inputs WHERE inbox_id=?",
            (payload["inboxId"],),
        )
        if included:
            return finish(**batch, handled=False)
        waiting = "bounded_backlog"
    db.execute(
        "UPDATE jobs SET state='queued',available_ms=? WHERE id=?", (now_ms() + 1000, job_id)
    )
    return {**payload, "waiting": waiting}
