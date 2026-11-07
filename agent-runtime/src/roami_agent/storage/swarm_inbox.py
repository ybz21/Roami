"""One business message, with separate read and response receipts per recipient."""

import hashlib

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row, rows

KINDS = {"progress", "question", "blocker", "handoff", "reply"}


def member_for_task(db, swarm_id, task_id):
    return row(
        db,
        "SELECT m.id FROM swarm_members m JOIN swarm_member_work b ON b.member_id=m.id "
        "JOIN swarm_work_items w ON w.id=b.work_id WHERE m.swarm_id=? AND w.task_id=?",
        (swarm_id, task_id),
    )


def record_post(db, group, spec, author, task_id, binding, delivery_key):
    kind = spec.get("kind") or "progress"
    key, reply_to, recipient = (
        spec.get("messageKey"),
        spec.get("replyTo"),
        spec.get("recipientMemberId"),
    )
    if (
        not isinstance(kind, str)
        or kind not in KINDS
        or key is not None
        and (not isinstance(key, str) or not key.strip() or len(key) > 200)
        or reply_to is not None
        and (type(reply_to) is not int or reply_to < 1)
        or kind == "reply"
        and reply_to is None
    ):
        raise DomainError("INVALID_SWARM_MESSAGE")
    source = member_for_task(db, group["id"], task_id) if binding and task_id else None
    if binding and task_id and not source:
        raise DomainError("SWARM_MEMBER_REQUIRED", 403)
    revision, run = None, None
    author_kind = "member" if source else "main" if binding else "human"
    if source:
        attempt = row(db, "SELECT task_revision FROM task_attempts WHERE id=?", (binding["runId"],))
        revision, run = attempt["task_revision"], binding["runId"]
        author_key = encoded(["member", source["id"], task_id, revision, run])
    else:
        author_key = encoded(
            ["main", group["conversation_id"]] if binding else ["human", group["owner_id"]]
        )
    digest = hashlib.sha256(
        encoded([spec["text"].strip(), kind, reply_to, recipient]).encode()
    ).hexdigest()
    if key is not None:
        previous = row(
            db,
            "SELECT post_id,payload_sha256 FROM swarm_post_routes WHERE swarm_id=? AND author_key=? AND message_key=?",
            (group["id"], author_key, key),
        )
        if previous:
            if previous["payload_sha256"] != digest:
                raise DomainError("SWARM_MESSAGE_KEY_CONFLICT", 409)
            return {"id": previous["post_id"], "swarmId": group["id"]}, False
    parent = None
    if reply_to is not None:
        parent = row(
            db,
            "SELECT p.id,r.author_member_id,r.author_kind FROM swarm_posts p LEFT JOIN swarm_post_routes r ON r.post_id=p.id "
            "WHERE p.id=? AND p.swarm_id=?",
            (reply_to, group["id"]),
        )
        if not parent:
            raise DomainError("SWARM_MESSAGE_SCOPE_CONFLICT", 409)
    if recipient is not None and not row(
        db, "SELECT id FROM swarm_members WHERE id=? AND swarm_id=?", (recipient, group["id"])
    ):
        raise DomainError("SWARM_MESSAGE_SCOPE_CONFLICT", 409)
    post_id = db.execute(
        "INSERT INTO swarm_posts(swarm_id,author,text,task_id,created_ms,delivery_key) VALUES(?,?,?,?,?,?)",
        (group["id"], author, spec["text"].strip(), task_id, now_ms(), delivery_key),
    ).lastrowid
    db.execute(
        "INSERT INTO swarm_post_routes(post_id,swarm_id,author_key,author_kind,author_member_id,kind,message_key,"
        "payload_sha256,source_task_revision,source_run_id,recipient_member_id,reply_to_post_id) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            post_id,
            group["id"],
            author_key,
            author_kind,
            source["id"] if source else None,
            kind,
            key,
            digest,
            revision,
            run,
            recipient,
            reply_to,
        ),
    )
    targets = set()
    if kind in {"question", "blocker", "handoff"}:
        if author_kind != "main":
            targets.add((group["conversation_id"], None))
        if recipient and (not source or recipient != source["id"]):
            targets.add((None, recipient))
    elif kind == "reply" and parent:
        if recipient and (not source or recipient != source["id"]):
            targets.add((None, recipient))
        elif parent["author_member_id"] and (
            not source or parent["author_member_id"] != source["id"]
        ):
            targets.add((None, parent["author_member_id"]))
        elif parent["author_kind"] == "main" and author_kind != "main":
            targets.add((group["conversation_id"], None))
        if source:
            db.execute(
                "UPDATE swarm_inbox SET handled_post_id=? WHERE post_id=? AND member_id=? AND handled_post_id IS NULL",
                (post_id, reply_to, source["id"]),
            )
        elif author_kind == "main":
            db.execute(
                "UPDATE swarm_inbox SET handled_post_id=? WHERE post_id=? AND main_conversation_id=? AND handled_post_id IS NULL",
                (post_id, reply_to, group["conversation_id"]),
            )
    for main_id, member_id in targets:
        db.execute(
            "INSERT INTO swarm_inbox(post_id,main_conversation_id,member_id,created_ms) VALUES(?,?,?,?)",
            (post_id, main_id, member_id, now_ms()),
        )
    if author_kind == "member" and (group["conversation_id"], None) in targets:
        from roami_agent.storage.swarm_inbox_wakeup import queue_post

        queue_post(db, group, post_id)
    return {"id": post_id, "swarmId": group["id"]}, True


def inbox(db, group, *, member_id=None, limit=20, before=None, mark_read=False):
    if (
        type(limit) is not int
        or not 1 <= limit <= 100
        or before is not None
        and (type(before) is not int or before < 1)
    ):
        raise DomainError("INVALID_SWARM_INBOX")
    if member_id is not None and not row(
        db, "SELECT id FROM swarm_members WHERE id=? AND swarm_id=?", (member_id, group["id"])
    ):
        raise DomainError("SWARM_MEMBER_REQUIRED", 403)
    receiver, receiver_id = (
        ("i.member_id", member_id)
        if member_id
        else ("i.main_conversation_id", group["conversation_id"])
    )
    items = rows(
        db,
        "SELECT i.id,i.post_id AS postId,i.created_ms AS createdMs,i.read_ms AS readMs,"
        "p.author,r.author_kind AS authorKind,p.text,p.task_id AS taskId,r.kind,r.source_task_revision AS taskRevision,"
        "r.source_run_id AS runId,r.author_member_id AS authorMemberId,r.reply_to_post_id AS replyTo,"
        "CASE WHEN r.source_run_id IS NULL THEN 1 WHEN t.revision=r.source_task_revision "
        "AND r.source_run_id=(SELECT id FROM task_attempts a WHERE a.task_id=t.id AND a.task_revision=t.revision ORDER BY a.attempt_no DESC LIMIT 1) "
        "THEN 1 ELSE 0 END AS sourceCurrent "
        "FROM swarm_inbox i JOIN swarm_post_routes r ON r.post_id=i.post_id "
        "JOIN swarm_posts p ON p.id=i.post_id LEFT JOIN tasks t ON t.id=p.task_id "
        "WHERE r.swarm_id=? AND " + receiver + "=? AND i.handled_post_id IS NULL "
        "AND (? IS NULL OR i.id<?) ORDER BY i.id DESC LIMIT ?",
        (group["id"], receiver_id, before, before, limit),
    )
    if mark_read:
        stamp = now_ms()
        for item in items:
            if item["readMs"] is None:
                db.execute(
                    "UPDATE swarm_inbox SET read_ms=? WHERE id=? AND read_ms IS NULL",
                    (stamp, item["id"]),
                )
                item["readMs"] = stamp
    for item in items:
        item["sourceCurrent"] = bool(item["sourceCurrent"])
    return {
        "swarmId": group["id"],
        "memberId": member_id,
        "items": items,
        "nextBefore": items[-1]["id"] if len(items) == limit else None,
    }
