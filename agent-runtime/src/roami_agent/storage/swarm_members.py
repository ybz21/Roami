"""Persistent role identities and immutable requests for each execution revision."""

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.storage.database import row, rows

EXECUTORS = {"native", "codex", "claude", "opencode", "pi"}


def member_for_plan(db, group, name, executor, duty, member_id=None):
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name.strip()) > 80
        or name.strip().casefold() in {"main", "leader"}
        or not isinstance(executor, str)
        or executor not in EXECUTORS
        or not isinstance(duty, str)
        or not duty.strip()
        or len(duty) > 8000
    ):
        raise DomainError("INVALID_SWARM_MEMBER")
    name = name.strip()
    member = row(db, "SELECT * FROM swarm_members WHERE swarm_id=? AND name=?", (group["id"], name))
    if member_id and (not member or member["id"] != member_id):
        raise DomainError("SWARM_MEMBER_NOT_FOUND", 404)
    if member:
        if member["executor"] != executor:
            raise DomainError("SWARM_MEMBER_EXECUTOR_CONFLICT", 409)
        from roami_agent.storage.member_instances import ensure_native_instance

        ensure_native_instance(db, member)
        return member
    ident = identity()
    db.execute(
        "INSERT INTO swarm_members(id,swarm_id,name,executor,duty,created_ms) VALUES(?,?,?,?,?,?)",
        (ident, group["id"], name, executor, duty.strip(), now_ms()),
    )
    member = row(db, "SELECT * FROM swarm_members WHERE id=?", (ident,))
    from roami_agent.storage.member_instances import ensure_native_instance

    ensure_native_instance(db, member)
    return member


def record_round(db, task_id, revision, source_message_id, text):
    binding = row(
        db,
        "SELECT m.id FROM swarm_members m JOIN swarm_member_work b ON b.member_id=m.id "
        "JOIN swarm_work_items w ON w.id=b.work_id WHERE w.task_id=?",
        (task_id,),
    )
    if binding:
        db.execute(
            "INSERT OR IGNORE INTO swarm_member_rounds(member_id,task_id,revision,source_message_id,request_text,created_ms) VALUES(?,?,?,?,?,?)",
            (binding["id"], task_id, revision, source_message_id, text, now_ms()),
        )


def member_list(db, sid, work):
    from roami_agent.storage.member_instances import instance_summaries

    instances = instance_summaries(db, sid)
    by_id = {item["id"]: item for item in work}
    members = rows(
        db,
        "SELECT m.id,m.swarm_id,m.name,m.executor,m.created_ms,m.legacy,substr(m.duty,1,200) AS dutyPreview,b.work_id AS workId,(SELECT COUNT(*) FROM swarm_member_rounds r WHERE r.member_id=m.id) AS roundCount "
        "FROM swarm_members m LEFT JOIN swarm_member_work b ON b.member_id=m.id AND b.work_id=m.current_work_id WHERE m.swarm_id=? ORDER BY m.rowid",
        (sid,),
    )
    for member in members:
        item = by_id.get(member["workId"])
        member.update(
            taskId=item["task_id"] if item else None,
            taskRevision=item["revision"] if item else None,
            state=item["state"] if item else "unassigned",
            memoryPath="members/" + member["id"] + "/memory.md",
            instance=instances.get(member["id"]),
        )
        if item:
            item["memberId"] = member["id"]
    return members


def visible_source(db, owner, message_id):
    return bool(
        row(
            db,
            "SELECT m.id FROM messages m JOIN conversations c ON c.id=m.conversation_id "
            "WHERE m.id=? AND c.owner_id=? AND c.deleted_ms IS NULL AND m.deleted_ms IS NULL AND m.status!='deleted' "
            "AND NOT EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=? AND o.message_id=m.id)",
            (message_id, owner, owner),
        )
    )


def round_page(db, owner, member_id, before=None, limit=20):
    page = rows(
        db,
        "SELECT * FROM swarm_member_rounds WHERE member_id=? AND (? IS NULL OR id<?) ORDER BY id DESC LIMIT ?",
        (member_id, before, before, limit + 1),
    )
    more = len(page) > limit
    page = page[:limit]
    source = row(
        db,
        "SELECT g.conversation_id FROM swarm_members m JOIN swarm_groups g ON g.id=m.swarm_id WHERE m.id=?",
        (member_id,),
    )
    for entry in page:
        task = row(db, "SELECT * FROM tasks WHERE id=?", (entry["task_id"],))
        if (
            not task
            or task["owner_id"] != owner
            or task["origin_conversation_id"] != source["conversation_id"]
        ):
            raise DomainError("SWARM_MEMBER_BINDING_CONFLICT", 409)
        if (
            not visible_source(db, owner, task["origin_message_id"])
            or not entry["legacy"]
            and not entry["source_message_id"]
            or entry["source_message_id"]
            and not visible_source(db, owner, entry["source_message_id"])
        ):
            entry["request_text"] = None
            entry.update(
                sourceUnavailable=True,
                attempts=[],
                artifacts=[],
                state="unknown",
                attemptsTruncated=False,
                artifactsTruncated=False,
            )
            continue
        attempts = rows(
            db,
            "SELECT id AS runId,attempt_no AS attemptNo,state,session_id AS sessionId,agent_conversation_id AS providerConversationId,native_branch_id AS branchId,started_ms AS startedMs,finished_ms AS finishedMs "
            "FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 21",
            (entry["task_id"], entry["revision"]),
        )
        entry["attemptsTruncated"] = len(attempts) > 20
        entry["attempts"] = attempts[:20]
        from roami_agent.storage.swarm_evidence import evidence

        artifacts = evidence(db, task, {"id": attempts[0]["runId"]}) if attempts else []
        entry["artifacts"] = artifacts[:50]
        entry["artifactsTruncated"] = len(artifacts) > 50
        final = (
            row(
                db,
                "SELECT kind FROM events WHERE task_id=? AND json_extract(payload_json,'$.runId')=? "
                "AND kind IN ('task.succeeded','task.waiting_user','task.failed','task.cancelled','task.interrupted') ORDER BY id DESC LIMIT 1",
                (entry["task_id"], attempts[0]["runId"]),
            )
            if attempts
            else None
        )
        entry["state"] = (
            "unknown"
            if attempts and attempts[0]["state"] == "unknown"
            else task["state"]
            if task and task["revision"] == entry["revision"]
            else final["kind"].removeprefix("task.")
            if final
            else "unknown"
        )
    return {"items": page, "hasMore": more, "nextBefore": page[-1]["id"] if more else None}
