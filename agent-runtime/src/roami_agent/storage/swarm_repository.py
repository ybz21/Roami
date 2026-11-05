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
    if task["revision"] < item["required_task_revision"]:
        state = "blocked"
    return state, task


def dependency_task_ready(db, dep):
    upstream = row(
        db,
        "SELECT t.*,w.required_task_revision FROM swarm_work_items w LEFT JOIN tasks t ON t.id=w.task_id WHERE w.id=?",
        (dep["upstream_id"],),
    )
    if (
        not upstream
        or upstream["state"] != "succeeded"
        or upstream["revision"] != dep["task_revision"]
        or upstream["revision"] < upstream["required_task_revision"]
    ):
        return False
    return not dep["artifact_id"] or bool(
        row(
            db,
            "SELECT a.id FROM artifacts a JOIN task_attempts r ON r.id=json_extract(a.metadata_json,'$.runId') WHERE a.id=? AND a.task_id=? AND r.task_id=a.task_id AND r.task_revision=? AND a.purged_ms IS NULL AND a.deleted_ms IS NULL",
            (dep["artifact_id"], upstream["id"], upstream["revision"]),
        )
    )


def dependency_ready(db, dep, *, cache=None):
    if not dependency_task_ready(db, dep):
        return False
    cache = {} if cache is None else cache
    root = dep["upstream_id"]
    visiting = set()
    pending = [(root, None)]
    while pending:
        ident, parents = pending.pop()
        if ident in cache:
            continue
        if parents is not None:
            visiting.discard(ident)
            cache[ident] = all(cache.get(parent["upstream_id"], False) for parent in parents)
        elif ident in visiting:
            cache[ident] = False
        else:
            parents = rows(db, "SELECT * FROM swarm_dependencies WHERE work_id=?", (ident,))
            if not all(dependency_task_ready(db, parent) for parent in parents):
                cache[ident] = False
                continue
            visiting.add(ident)
            pending.append((ident, parents))
            pending.extend((parent["upstream_id"], None) for parent in parents)
    return cache[root]


def task_dependencies_ready(db, task):
    work = row(db, "SELECT * FROM swarm_work_items WHERE task_id=?", (task["id"],))
    if not work:
        return True
    if task["revision"] < work["required_task_revision"]:
        return False
    cache = {}
    return all(
        dependency_ready(db, dep, cache=cache)
        for dep in rows(db, "SELECT * FROM swarm_dependencies WHERE work_id=?", (work["id"],))
    )


def snapshot(db, owner, swarm_id):
    value = group(db, owner, swarm_id)
    work = rows(db, "SELECT * FROM swarm_work_items WHERE swarm_id=? ORDER BY rowid", (swarm_id,))
    dependency_cache = {}
    for item in work:
        item["deliverables"] = json.loads(item.pop("deliverables_json"))
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
        from roami_agent.storage.swarm_evidence import evidence

        attempt = (
            row(db, "SELECT * FROM task_attempts WHERE id=?", (item["attempt"]["runId"],))
            if item["attempt"]
            else None
        )
        accepted = (
            row(
                db,
                "SELECT json_extract(payload_json,'$.result.verification') AS verification FROM events "
                "WHERE task_id=? AND json_extract(payload_json,'$.runId')=? "
                "AND kind IN ('task.succeeded','task.waiting_user','task.failed','task.interrupted') ORDER BY id DESC LIMIT 1",
                (task["id"], attempt["id"]),
            )
            if task and attempt
            else None
        )
        item["evidence"] = {
            "artifacts": evidence(db, task, attempt) if task and attempt else [],
            "verification": json.loads(accepted["verification"])
            if accepted and accepted["verification"]
            else None,
        }
        stale = any(
            not dependency_ready(
                db,
                {
                    "upstream_id": dep["upstreamId"],
                    "task_revision": dep["revision"],
                    "artifact_id": dep["artifactId"],
                },
                cache=dependency_cache,
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
        if (
            task
            and task["revision"] < item["required_task_revision"]
            or stale
            and (item["task_id"] or unhealthy)
        ):
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
    from roami_agent.storage.swarm_members import member_list

    members = member_list(db, swarm_id, work)
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
        "members": members,
        "memberProtocol": value["member_protocol"],
        "posts": posts,
        "mainMessages": main_messages,
        "mainState": main_turn["state"] if main_turn else "idle",
    }
