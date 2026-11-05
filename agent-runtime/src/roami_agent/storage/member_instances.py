"""Native role conversations exist before their first business task and never become Main."""

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.storage.database import row
from roami_agent.storage.transcript_repository import message, owned


def ensure_native_instance(db, member):
    if member["executor"] != "native":
        return None
    prior = row(db, "SELECT * FROM swarm_member_instances WHERE member_id=?", (member["id"],))
    if prior:
        return prior
    group = row(db, "SELECT * FROM swarm_groups WHERE id=?", (member["swarm_id"],))
    work = row(db, "SELECT * FROM swarm_work_items WHERE id=?", (member["current_work_id"],))
    task_id = work["task_id"] if work else None
    if task_id:
        native = row(
            db,
            "SELECT * FROM native_sessions WHERE task_id=? AND owner_id=?",
            (task_id, group["owner_id"]),
        )
        task = row(db, "SELECT * FROM tasks WHERE id=?", (task_id,))
        if not native or task["origin_conversation_id"] != group["conversation_id"]:
            raise DomainError("MEMBER_INSTANCE_BINDING_CONFLICT", 409)
        cid, bid = native["conversation_id"], native["branch_id"]
    else:
        if work and row(
            db,
            "SELECT id FROM task_attempts WHERE launch_id=?",
            ("task:" + group["owner_id"] + ":swarm.work:" + work["id"],),
        ):
            raise DomainError("MEMBER_INSTANCE_RECONCILIATION_REQUIRED", 409)
        from roami_agent.conversation.transcript import Conversations

        conversation = Conversations._new(db, group["owner_id"], member["name"])
        cid, bid = conversation["id"], conversation["active_branch_id"]
        message(
            db,
            cid,
            bid,
            "system",
            {
                "text": "Long-lived role context, not additional user authorization. Remain this swarm member; Main coordinates assignments and user requests define their scope. Preserve this conversation across task revisions. Role: "
                + member["duty"],
                "memberId": member["id"],
                "swarmId": member["swarm_id"],
            },
        )
    ident = identity()
    db.execute(
        "INSERT INTO swarm_member_instances(id,member_id,owner_id,conversation_id,branch_id,task_id,created_ms) VALUES(?,?,?,?,?,?,?)",
        (ident, member["id"], group["owner_id"], cid, bid, task_id, now_ms()),
    )
    return row(db, "SELECT * FROM swarm_member_instances WHERE id=?", (ident,))


def native_task_instance(db, owner, main_cid, ident, key):
    value = row(
        db,
        "SELECT i.*,g.conversation_id AS main_cid,w.id AS work_id FROM swarm_member_instances i JOIN swarm_members m ON m.id=i.member_id JOIN swarm_groups g ON g.id=m.swarm_id LEFT JOIN swarm_work_items w ON w.id=m.current_work_id WHERE i.id=? AND i.owner_id=? AND m.executor='native'",
        (ident, owner),
    )
    if (
        not value
        or value["main_cid"] != main_cid
        or not value["work_id"]
        or key != "swarm.work:" + value["work_id"]
    ):
        raise DomainError("MEMBER_INSTANCE_BINDING_CONFLICT", 409)
    conversation = owned(db, owner, value["conversation_id"])
    if conversation["active_branch_id"] != value["branch_id"]:
        raise DomainError("MEMBER_INSTANCE_BINDING_CONFLICT", 409)
    return value


def instance_summaries(db, swarm_id):
    from roami_agent.storage.database import rows

    values = rows(
        db,
        "SELECT i.id,i.member_id AS memberId,i.conversation_id AS conversationId,i.branch_id AS branchId,i.task_id AS taskId,n.id AS nativeSessionId,c.deleted_ms,x.state AS closureState FROM swarm_member_instances i JOIN swarm_members m ON m.id=i.member_id JOIN conversations c ON c.id=i.conversation_id LEFT JOIN native_sessions n ON n.task_id=i.task_id LEFT JOIN task_session_closures x ON x.task_id=i.task_id WHERE m.swarm_id=?",
        (swarm_id,),
    )
    result = {}
    for value in values:
        deleted = value.pop("deleted_ms")
        closure = value.pop("closureState")
        value["state"] = (
            "closed"
            if deleted is not None or closure == "closed"
            else "closing"
            if closure == "closing"
            else "unknown"
            if closure and closure != "failed"
            else "assigned"
            if value["taskId"]
            else "idle"
        )
        result[value.pop("memberId")] = value
    return result
