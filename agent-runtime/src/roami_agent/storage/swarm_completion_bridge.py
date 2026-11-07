"""Preserve result notification identity until the original Main consumes the fact."""

import json

from roami_agent.conversation.activity_events import activity_event as event
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row, rows
from roami_agent.storage.swarm_delegations import current_delegation
from roami_agent.storage.task_result_receipts import receipt_for_run

KIND = "swarm.coordinate"


def _delegation(db, task, run):
    candidates = rows(
        db,
        "SELECT m.swarm_id,m.id AS member_id FROM swarm_members m "
        "JOIN swarm_work_items w ON w.id=m.current_work_id AND w.task_id=? "
        "JOIN swarm_groups g ON g.id=m.swarm_id AND g.owner_id=? "
        "WHERE g.conversation_id=? AND g.scope_project_id IS NOT NULL "
        "AND EXISTS(SELECT 1 FROM swarm_goal_delegations d WHERE d.swarm_id=g.id AND d.revoked_ms IS NULL)",
        (task["id"], task["owner_id"], task["origin_conversation_id"]),
    )
    valid = []
    for candidate in candidates:
        try:
            delegation = current_delegation(
                db, task["owner_id"], candidate["swarm_id"], allow_paused=True
            )
        except DomainError:
            continue
        if candidate["member_id"] in json.loads(delegation["member_ids_json"]):
            valid.append(delegation)
    if len(valid) != 1:
        return None
    current = row(db, "SELECT revision FROM tasks WHERE id=?", (task["id"],))
    latest = row(
        db,
        "SELECT id FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
        (task["id"], run["task_revision"]),
    )
    if (
        not current
        or current["revision"] != run["task_revision"]
        or not latest
        or latest["id"] != run["id"]
    ):
        return None
    return valid[0]


def _original_authority(db, task, authorization):
    value = row(
        db,
        "SELECT d.*,g.scope_project_id,g.conversation_id FROM swarm_goal_delegations d "
        "JOIN swarm_groups g ON g.id=d.swarm_id AND g.owner_id=? WHERE d.id=? AND d.swarm_id=?",
        (task["owner_id"], authorization.get("delegationId"), authorization.get("swarmId")),
    )
    member = row(
        db,
        "SELECT m.id FROM swarm_members m JOIN swarm_member_work b ON b.member_id=m.id "
        "JOIN swarm_work_items w ON w.id=b.work_id WHERE m.id=? AND m.swarm_id=? AND w.task_id=?",
        (authorization.get("memberId"), authorization.get("swarmId"), task["id"]),
    )
    if (
        not value
        or not member
        or any(
            (
                value["conversation_id"] != task["origin_conversation_id"],
                value["scope_project_id"] != authorization.get("projectId"),
                task["id"] != authorization.get("taskId"),
                value["source_message_id"] != authorization.get("sourceMessageId"),
                value["source_sha256"] != authorization.get("sourceSha256"),
                value["source_quote"] != authorization.get("goalQuote"),
                member["id"] not in json.loads(value["member_ids_json"]),
            )
        )
    ):
        raise DomainError("SWARM_COORDINATION_SCOPE_CONFLICT", 403)
    return value


def route(db, task, run, completion, completion_key):
    receipt = completion.get("executionReceipt")
    if not receipt:
        return False
    existing = row(db, "SELECT * FROM jobs WHERE dedupe_key=?", (completion_key,))
    if existing and existing["kind"] != KIND:
        return False
    authorization = json.loads(task["intent_json"]).get("coordinationAuthorization")
    delegation = (
        _original_authority(db, task, authorization)
        if authorization
        else _delegation(db, task, run)
    )
    if delegation is None:
        return False
    actual = receipt_for_run(db, task["id"], run["id"])
    if actual != receipt:
        raise DomainError("TASK_RESULT_RECEIPT_CONFLICT", 409)
    key = completion_key
    if existing and json.loads(existing["payload_json"])["executionReceipt"] != receipt:
        key += ":receipt:" + str(receipt["receiptId"])
    payload = {
        "swarmId": delegation["swarm_id"],
        "delegationId": delegation["id"],
        "executionReceipt": receipt,
    }
    inserted = db.execute(
        "INSERT OR IGNORE INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) VALUES(?,?,?,?,?,'queued',?)",
        (identity(), KIND, task["id"], key, encoded(payload), now_ms()),
    ).rowcount
    if inserted:
        event(
            db,
            task["origin_conversation_id"],
            "task." + completion["state"],
            completion,
            task_id=task["id"],
            key="coordination-completion:" + key,
        )
    return True


def _finish(db, job, payload, **receipt):
    result = {**payload, **receipt}
    db.execute(
        "UPDATE jobs SET state='done',payload_json=? WHERE id=?", (encoded(result), job["id"])
    )
    return result


def advance(db, job_id):
    job = row(db, "SELECT * FROM jobs WHERE id=? AND kind=?", (job_id, KIND))
    if not job:
        raise DomainError("SWARM_COORDINATION_RESULT_JOB_REQUIRED", 409)
    payload = json.loads(job["payload_json"])
    if job["state"] == "done":
        return payload
    if job["state"] not in {"queued", "running"}:
        raise DomainError("SWARM_COORDINATION_RESULT_JOB_NOT_CURRENT", 409)
    receipt = payload["executionReceipt"]
    task = row(db, "SELECT * FROM tasks WHERE id=?", (receipt["taskId"],))
    run = row(
        db,
        "SELECT * FROM task_attempts WHERE id=? AND task_id=?",
        (receipt["runId"], receipt["taskId"]),
    )
    if not task or not run:
        return _finish(db, job, payload, skipped="task_unavailable")
    delegation = _delegation(db, task, run)
    if (
        not delegation
        or delegation["id"] != payload["delegationId"]
        or delegation["swarm_id"] != payload["swarmId"]
    ):
        return _finish(db, job, payload, skipped="source_or_scope_unavailable")
    if receipt_for_run(db, task["id"], run["id"]) != receipt:
        return _finish(db, job, payload, skipped="result_superseded")
    observed = row(
        db,
        "SELECT manifest_id FROM swarm_result_observations WHERE delegation_id=? AND receipt_id=?",
        (delegation["id"], receipt["receiptId"]),
    )
    if observed:
        return _finish(db, job, payload, observedManifestId=observed["manifest_id"])
    frozen = row(
        db,
        "SELECT r.batch_id,b.turn_id FROM swarm_coordination_results r JOIN swarm_coordination_batches b ON b.id=r.batch_id "
        "WHERE r.delegation_id=? AND r.receipt_id=?",
        (delegation["id"], receipt["receiptId"]),
    )
    if frozen:
        return _finish(
            db, job, payload, batchId=frozen["batch_id"], turnId=frozen["turn_id"], observed=False
        )
    from roami_agent.storage.swarm_coordination import enqueue

    try:
        batch = enqueue(db, task["owner_id"], payload["swarmId"])
    except DomainError as exc:
        if exc.code not in {"MAIN_BUSY", "MAIN_WAITING_USER", "SWARM_COORDINATION_PAUSED"}:
            raise
        db.execute(
            "UPDATE jobs SET state='queued',available_ms=? WHERE id=?", (now_ms() + 1000, job_id)
        )
        return {**payload, "waiting": exc.code}
    if batch is None:
        return _finish(db, job, payload, skipped="result_not_pending")
    included = row(
        db,
        "SELECT batch_id FROM swarm_coordination_results WHERE delegation_id=? AND receipt_id=?",
        (delegation["id"], receipt["receiptId"]),
    )
    if not included:
        # An older bounded backlog may have filled this batch; keep this notification queued.
        db.execute(
            "UPDATE jobs SET state='queued',available_ms=? WHERE id=?", (now_ms() + 1000, job_id)
        )
        return {**payload, "waiting": "bounded_backlog"}
    return _finish(
        db, job, payload, batchId=batch["batchId"], turnId=batch["turnId"], observed=False
    )
