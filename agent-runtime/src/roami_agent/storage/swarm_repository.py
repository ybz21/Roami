"""Owned collaboration records; execution state remains in Tasks."""

import hashlib
import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import event, row, rows
from roami_agent.storage.transcript_repository import owned


def group(db, owner, swarm_id):
    value = row(db, "SELECT * FROM swarm_groups WHERE id=? AND owner_id=?", (swarm_id, owner))
    if not value:
        raise DomainError("SWARM_NOT_FOUND", 404)
    owned(db, owner, value["conversation_id"])
    return value


def receipt(db, owner, key, payload, write):
    if not isinstance(key, str) or not key.strip() or len(key) > 200:
        raise DomainError("INVALID_REQUEST_KEY")
    digest = hashlib.sha256(encoded(payload).encode()).hexdigest()
    prior = row(db, "SELECT * FROM swarm_commands WHERE owner_id=? AND command_key=?", (owner, key))
    if prior:
        if prior["digest"] != digest:
            raise DomainError("REQUEST_KEY_CONFLICT", 409)
        return json.loads(prior["receipt_json"])
    result = write()
    db.execute("INSERT INTO swarm_commands VALUES(?,?,?,?)", (owner, key, digest, encoded(result)))
    return result


def changed(db, value, kind="swarm.changed"):
    db.execute("UPDATE swarm_groups SET updated_ms=? WHERE id=?", (now_ms(), value["id"]))
    event(
        db, value["conversation_id"], kind, {"swarmId": value["id"], "revision": value["revision"]}
    )


def enqueue(db, swarm_id, key):
    db.execute(
        "INSERT OR IGNORE INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) "
        "VALUES(?,'swarm.advance',?,?,?,'queued',?)",
        (identity(), swarm_id, "swarm:" + key, encoded({}), now_ms()),
    )


def work_state(db, item):
    if item["dispatch_error"]:
        return "blocked", None
    if not item["task_id"]:
        return "queued", None
    task = row(db, "SELECT * FROM tasks WHERE id=?", (item["task_id"],))
    attempt = row(
        db,
        "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
        (task["id"], task["revision"]),
    )
    state = task["state"]
    if attempt and attempt["state"] == "unknown":
        state = "unknown"
    return state, task


def dependency_ready(db, dep):
    upstream = row(
        db,
        "SELECT t.* FROM swarm_work_items w LEFT JOIN tasks t ON t.id=w.task_id WHERE w.id=?",
        (dep["upstream_id"],),
    )
    if (
        not upstream
        or upstream["state"] != "succeeded"
        or upstream["revision"] != dep["task_revision"]
    ):
        return False
    if dep["artifact_id"]:
        return bool(
            row(
                db,
                "SELECT a.id FROM artifacts a JOIN task_attempts r ON r.id=json_extract(a.metadata_json,'$.runId') WHERE a.id=? AND a.task_id=? AND r.task_id=a.task_id AND r.task_revision=? AND a.purged_ms IS NULL AND a.deleted_ms IS NULL",
                (dep["artifact_id"], upstream["id"], upstream["revision"]),
            )
        )
    return True


def snapshot(db, owner, swarm_id):
    value = group(db, owner, swarm_id)
    work = rows(db, "SELECT * FROM swarm_work_items WHERE swarm_id=? ORDER BY rowid", (swarm_id,))
    for item in work:
        item["dependencies"] = rows(
            db,
            "SELECT upstream_id AS upstreamId,task_revision AS revision,artifact_id AS artifactId FROM swarm_dependencies WHERE work_id=?",
            (item["id"],),
        )
        item["state"], task = work_state(db, item)
        item["revision"] = task["revision"] if task else None
        item["attempt"] = (
            row(
                db,
                "SELECT id AS runId,state,session_id AS sessionId,finished_ms AS finishedMs,substr(json_extract(result_json,'$.summary'),1,800) AS summary FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
                (task["id"], task["revision"]),
            )
            if task
            else None
        )
        stale = any(
            not dependency_ready(
                db,
                {
                    "upstream_id": dep["upstreamId"],
                    "task_revision": dep["revision"],
                    "artifact_id": dep["artifactId"],
                },
            )
            for dep in item["dependencies"]
        )
        unhealthy = any(
            (
                upstream := row(
                    db,
                    "SELECT t.state,t.revision FROM swarm_work_items w LEFT JOIN tasks t ON t.id=w.task_id WHERE w.id=?",
                    (dep["upstreamId"],),
                )
            )
            and (
                upstream["state"] in {"failed", "interrupted", "cancelled", "waiting_user"}
                or upstream["revision"]
                and upstream["revision"] != dep["revision"]
            )
            for dep in item["dependencies"]
        )
        if stale and (item["task_id"] or unhealthy):
            item["state"] = "blocked"
            item["dispatch_error"] = item["dispatch_error"] or "SWARM_DEPENDENCY_NOT_VERIFIED"
    all_ids = {item["id"] for item in work}
    graph = {item["id"]: [dep["upstreamId"] for dep in item["dependencies"]] for item in work}

    def covers(ident):
        reached = set()
        pending = list(graph[ident])
        while pending:
            upstream = pending.pop()
            if upstream in reached:
                continue
            reached.add(upstream)
            pending.extend(graph.get(upstream, []))
        return all_ids - {ident} <= reached

    integration_complete = any(item["integration"] and covers(item["id"]) for item in work)
    states = [item["state"] for item in work]
    state = (
        "planning"
        if not states
        else "done"
        if all(st == "succeeded" for st in states) and integration_complete
        else "cancelled"
        if all(st in {"succeeded", "cancelled"} for st in states) and "cancelled" in states
        else "blocked"
        if any(st in {"failed", "blocked", "unknown", "interrupted"} for st in states)
        else "review"
        if all(st == "succeeded" for st in states)
        or any(st in {"verifying", "waiting_user"} for st in states)
        else "running"
    )
    sequence = db.execute(
        "SELECT COALESCE(MAX(id),0) FROM events WHERE conversation_id=?",
        (value["conversation_id"],),
    ).fetchone()[0]
    posts = rows(
        db,
        "SELECT id,author,text,task_id AS taskId,created_ms AS createdMs,CASE WHEN author!='human' OR turn_id IS NOT NULL OR delivery_json IS NOT NULL THEN 'accepted' ELSE 'pending' END AS deliveryState FROM swarm_posts WHERE swarm_id=? ORDER BY id DESC LIMIT 100",
        (swarm_id,),
    )[::-1]
    main_messages = rows(
        db,
        "SELECT id,role,substr(json_extract(native_content(content_json),'$.text'),1,16000) AS text,created_ms AS createdMs FROM messages WHERE turn_id IN (SELECT turn_id FROM swarm_posts WHERE swarm_id=? AND turn_id IS NOT NULL UNION SELECT j.aggregate_id FROM jobs j WHERE j.kind='turn.run' AND json_extract(j.payload_json,'$.completion.taskId') IN (SELECT task_id FROM swarm_work_items WHERE swarm_id=?)) AND role='assistant' AND deleted_ms IS NULL ORDER BY created_ms DESC LIMIT 50",
        (swarm_id, swarm_id),
    )[::-1]
    main_turn = row(
        db,
        "SELECT state FROM turns WHERE id IN (SELECT turn_id FROM swarm_posts WHERE swarm_id=? AND turn_id IS NOT NULL UNION SELECT aggregate_id FROM jobs WHERE kind='turn.run' AND json_extract(payload_json,'$.completion.taskId') IN (SELECT task_id FROM swarm_work_items WHERE swarm_id=?)) ORDER BY created_ms DESC LIMIT 1",
        (swarm_id, swarm_id),
    )
    return {
        "id": swarm_id,
        "name": value["name"],
        "goal": value["goal"],
        "engine": "roami_v2",
        "mainConversationId": value["conversation_id"],
        "target": json.loads(value["target_json"]),
        "revision": value["revision"],
        "paused": bool(value["paused"]),
        "archived": bool(value["archived"]),
        "state": state,
        "sequence": sequence,
        "work": work,
        "posts": posts,
        "mainMessages": main_messages,
        "mainState": main_turn["state"] if main_turn else "idle",
    }
