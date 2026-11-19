"""A member explicitly yields its current input so its original Main can answer."""

import json

from roami_agent.dispatch.task_cancellation import request_task_cancellation
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row
from roami_agent.storage.swarm_delegations import current_delegation

KIND = "task.yield"


def current_source(db, owner, payload):
    task = row(db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (payload["taskId"], owner))
    if not task or task["revision"] != payload["revision"]:
        raise DomainError("TASK_RESULT_SUPERSEDED", 409)
    run = row(
        db,
        "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
        (task["id"], task["revision"]),
    )
    if not run or run["id"] != payload["runId"]:
        raise DomainError("TASK_RESULT_SUPERSEDED", 409)
    goal = current_delegation(db, owner, payload["swarmId"], allow_paused=True)
    if (
        payload.get("delegationId", goal["id"]) != goal["id"]
        or payload.get("delegationRevision", goal["revision"]) != goal["revision"]
    ):
        raise DomainError("SWARM_DELEGATION_REQUIRED", 409)
    source = row(
        db,
        "SELECT p.id FROM swarm_posts p JOIN swarm_post_routes r ON r.post_id=p.id "
        "JOIN swarm_members m ON m.id=r.author_member_id "
        "JOIN swarm_work_items w ON w.id=m.current_work_id "
        "WHERE p.id=? AND p.swarm_id=? AND p.task_id=? AND r.author_kind='member' "
        "AND r.kind IN ('question','blocker') AND r.source_task_revision=? AND r.source_run_id=? "
        "AND m.swarm_id=p.swarm_id AND w.swarm_id=p.swarm_id AND w.task_id=p.task_id "
        "AND m.id IN (SELECT value FROM json_each(?))",
        (
            payload["postId"],
            payload["swarmId"],
            task["id"],
            task["revision"],
            run["id"],
            goal["member_ids_json"],
        ),
    )
    if not source:
        raise DomainError("SWARM_MEMBER_REQUIRED", 403)
    return task, run, goal


def request(db, team, binding, spec, post_id):
    if not binding or not binding.get("taskId") or spec.get("kind") not in {"question", "blocker"}:
        raise DomainError("SWARM_MEMBER_REQUIRED", 403)
    if type(binding.get("taskRevision")) is not int or binding["taskRevision"] < 1:
        raise DomainError("TASK_REVISION_REQUIRED", 409)
    payload = {
        "owner": team["owner_id"],
        "swarmId": team["id"],
        "taskId": binding["taskId"],
        "runId": binding["runId"],
        "revision": binding["taskRevision"],
        "postId": post_id,
        "commandKey": spec["commandKey"],
        "scopeProjectId": team["scope_project_id"] or "",
    }
    task, run, goal = current_source(db, team["owner_id"], payload)
    if (
        task["state"] != "running"
        or run["state"] != "running"
        or run["executor_kind"] != "cli"
        or run["result_json"]
    ):
        raise DomainError("SWARM_MEMBER_YIELD_UNAVAILABLE", 409)
    payload["delegationId"] = goal["id"]
    payload["delegationRevision"] = goal["revision"]
    key = "task.yield:" + run["id"] + ":" + str(post_id)
    db.execute(
        "INSERT OR IGNORE INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) "
        "VALUES(?,?,?,?,?,'queued',?)",
        (identity(), KIND, task["id"], key, encoded(payload), now_ms()),
    )
    job = row(db, "SELECT id FROM jobs WHERE dedupe_key=?", (key,))
    return {"operationId": job["id"], "acceptedOnly": True, "yieldState": "requested"}


def advance(db, job_id):
    job = row(db, "SELECT * FROM jobs WHERE id=? AND kind=?", (job_id, KIND))
    if not job or job["state"] not in {"queued", "running", "done"}:
        raise DomainError("SWARM_MEMBER_YIELD_NOT_CURRENT", 409)
    payload = json.loads(job["payload_json"])
    if job["state"] == "done":
        return payload

    def finish(**result):
        value = {**payload, **result}
        db.execute(
            "UPDATE jobs SET state='done',payload_json=? WHERE id=?", (encoded(value), job_id)
        )
        return value

    try:
        task, run, _ = current_source(db, payload["owner"], payload)
    except DomainError as exc:
        return finish(skipped=exc.code)
    if task["state"] != "running" or run["result_json"]:
        return finish(skipped="task_not_running")
    command = row(
        db,
        "SELECT receipt_json FROM swarm_commands WHERE owner_id=? AND scope_project_id=? AND command_key=?",
        (payload["owner"], payload["scopeProjectId"], payload["commandKey"]),
    )
    receipt = json.loads(command["receipt_json"]) if command else {}
    if receipt.get("id") != payload["postId"] or receipt.get("operationId") != job_id:
        raise DomainError("SWARM_MEMBER_YIELD_RECEIPT_UNAVAILABLE", 409)
    request_task_cancellation(db, payload["owner"], task["id"])
    cancellation = row(
        db,
        "SELECT id FROM events WHERE task_id=? AND kind='task.cancelling' ORDER BY id DESC LIMIT 1",
        (task["id"],),
    )
    return finish(cancellationEventId=cancellation["id"])


def yield_stop_request(db, task, run):
    job = row(
        db,
        "SELECT id,payload_json FROM jobs WHERE kind=? AND aggregate_id=? AND state='done' "
        "AND json_extract(payload_json,'$.runId')=? "
        "AND json_extract(payload_json,'$.revision')=? "
        "AND json_extract(payload_json,'$.owner')=? "
        "AND EXISTS(SELECT 1 FROM events e WHERE e.id=json_extract(jobs.payload_json,'$.cancellationEventId') "
        "AND e.task_id=jobs.aggregate_id AND e.kind='task.cancelling') ORDER BY rowid DESC LIMIT 1",
        (KIND, task["id"], run["id"], task["revision"], task["owner_id"]),
    )
    return {**json.loads(job["payload_json"]), "operationId": job["id"]} if job else None


def current_yield_request(db, task, run):
    payload = yield_stop_request(db, task, run)
    if payload is None:
        return None
    cancellation = row(
        db,
        "SELECT id FROM events WHERE task_id=? AND kind='task.cancelling' ORDER BY id DESC LIMIT 1",
        (task["id"],),
    )
    if not cancellation or cancellation["id"] != payload["cancellationEventId"]:
        return None
    try:
        current_source(db, task["owner_id"], payload)
    except DomainError:
        return None
    return {"postId": payload["postId"], "operationId": payload["operationId"]}
