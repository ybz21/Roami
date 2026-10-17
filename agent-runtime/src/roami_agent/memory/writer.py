"""Validate source snapshots and commit inferred candidates separately from confirmed facts."""

import hashlib

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.retrieval.tokens import search_tokens
from roami_agent.storage.database import row, rows
from roami_agent.storage.transcript_repository import owned


def source_snapshot(db, owner, message_id):
    if message_id.startswith("artifact:"):
        source = row(
            db,
            "SELECT a.*,COALESCE(m.conversation_id,t.origin_conversation_id) AS conversation_id,"
            "m.branch_id FROM artifacts a LEFT JOIN messages m ON m.id=a.message_id "
            "LEFT JOIN tasks t ON t.id=a.task_id LEFT JOIN conversations c ON c.id=COALESCE(m.conversation_id,t.origin_conversation_id) "
            "WHERE a.id=? AND a.owner_id=? AND a.deleted_ms IS NULL "
            "AND (c.id IS NULL OR (c.deleted_ms IS NULL AND c.owner_id=?)) "
            "AND (a.message_id IS NULL OR (m.id IS NOT NULL AND m.deleted_ms IS NULL AND m.status='completed'))",
            (message_id[9:], owner, owner),
        )
        if not source:
            raise DomainError("MEMORY_SOURCE_NOT_FOUND", 404)
        artifact_id = source["id"]
        source.update(
            id=message_id,
            artifact_id=artifact_id,
            message_id=None,
            event_id=None,
            kind="artifact",
            content_json=encoded(
                {
                    "text": source["name"],
                    "artifact": {
                        "id": artifact_id,
                        "name": source["name"],
                        "mimeType": source["mime_type"],
                        "sha256": source["sha256"],
                        "sizeBytes": source["size_bytes"],
                    },
                }
            ),
        )
        return source
    if message_id.startswith("event:"):
        source = row(
            db,
            "SELECT e.*,c.owner_id FROM events e JOIN conversations c ON c.id=e.conversation_id WHERE e.id=? AND c.owner_id=? AND c.deleted_ms IS NULL",
            (message_id[6:], owner),
        )
        if not source:
            raise DomainError("MEMORY_SOURCE_NOT_FOUND", 404)
        source.update(
            id=message_id,
            event_id=source["id"],
            message_id=None,
            branch_id=None,
            content_json=encoded([source["kind"], source["payload_json"]]),
        )
        source["sha256"] = hashlib.sha256(source["content_json"].encode()).hexdigest()
        return source
    source = row(
        db,
        "SELECT m.* FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE m.id=? AND c.owner_id=? AND c.deleted_ms IS NULL AND m.deleted_ms IS NULL AND m.status='completed'",
        (message_id, owner),
    )
    if not source:
        raise DomainError("MEMORY_SOURCE_NOT_FOUND", 404)
    source["sha256"] = hashlib.sha256(source["content_json"].encode()).hexdigest()
    source.update(message_id=source["id"], event_id=None)
    return source


def commit_memory(
    db,
    owner,
    title,
    body,
    source_ids,
    *,
    kind="fact",
    project_id=None,
    conversation_id=None,
    task_id=None,
    day_key=None,
    timezone=None,
    confirmed=False,
    expected_sources=None,
    source_watermark=None,
):
    if (
        not body.strip()
        or len(body) > 20_000
        or len(title) > 200
        or kind not in {"fact", "decision", "preference", "summary"}
        or not 1 <= len(source_ids) <= 16
    ):
        raise DomainError("INVALID_MEMORY")
    if conversation_id:
        owned(db, owner, conversation_id)
    task = (
        row(db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (task_id, owner))
        if task_id
        else None
    )
    if task_id and not task:
        raise DomainError("TASK_NOT_FOUND", 404)
    sources = [source_snapshot(db, owner, message_id) for message_id in dict.fromkeys(source_ids)]
    for source in sources:
        if source.get("artifact_id") and task and source.get("task_id") not in {None, task_id}:
            raise DomainError("MEMORY_SOURCE_SCOPE_MISMATCH", 409)
        if expected_sources is not None and expected_sources.get(source["id"]) != source["sha256"]:
            raise DomainError("MEMORY_SOURCE_CHANGED", 409)
        if (
            conversation_id
            and source["conversation_id"] != conversation_id
            and (
                not task
                or task["origin_conversation_id"] != conversation_id
                or not row(
                    db,
                    "SELECT id FROM task_attempts WHERE task_id=? AND native_branch_id=?",
                    (task_id, source["branch_id"]),
                )
            )
        ):
            raise DomainError("MEMORY_SOURCE_SCOPE_MISMATCH", 409)
        if (
            task
            and source["conversation_id"] != task["origin_conversation_id"]
            and not row(
                db,
                "SELECT id FROM task_attempts WHERE task_id=? AND native_branch_id=?",
                (task_id, source["branch_id"]),
            )
        ):
            raise DomainError("MEMORY_SOURCE_SCOPE_MISMATCH", 409)
    dimensions = [kind, project_id, conversation_id, task_id, title]
    if day_key is not None:
        dimensions.extend([day_key, timezone])
    key = hashlib.sha256(encoded(dimensions).encode()).hexdigest()
    for source in sources:
        tombstone = row(
            db,
            "SELECT created_ms FROM memory_tombstones WHERE owner_id=? AND source_fingerprint=?"
            + (" AND canonical_key=?" if confirmed else ""),
            (owner, source["sha256"], key) if confirmed else (owner, source["sha256"]),
        )
        if tombstone:
            prior_source = row(
                db,
                "SELECT 1 FROM memory_sources s JOIN memory_records r ON r.id=s.memory_id WHERE r.owner_id=? AND r.canonical_key=? AND s.source_key=?",
                (owner, key, source["id"]),
            )
            if not confirmed or prior_source or source["created_ms"] < tombstone["created_ms"]:
                raise DomainError("MEMORY_FORGOTTEN", 409)
        if row(
            db,
            "SELECT 1 FROM context_omissions WHERE owner_id=? AND message_id=?",
            (owner, source["id"]),
        ):
            raise DomainError("MEMORY_FORGOTTEN", 409)
    existing = rows(
        db,
        "SELECT * FROM memory_records WHERE owner_id=? AND canonical_key=? ORDER BY revision DESC,created_ms DESC",
        (owner, key),
    )
    active = next((item for item in existing if item["state"] == "active"), None)
    if active and active["body"] == body:
        return active
    pending = next(
        (
            item
            for item in existing
            if item["state"] in {"candidate", "conflict"} and item["body"] == body
        ),
        None,
    )
    if pending and not confirmed:
        return pending
    state = "active" if confirmed else "conflict" if active else "candidate"
    ident, timestamp = identity(), now_ms()
    if confirmed:
        db.execute(
            "UPDATE memory_records SET state='superseded',valid_until_ms=?,updated_ms=? WHERE owner_id=? AND canonical_key=? AND state IN ('active','candidate','conflict')",
            (timestamp, timestamp, owner, key),
        )
    db.execute(
        "INSERT INTO memory_records(id,owner_id,kind,project_id,conversation_id,task_id,day_key,timezone,title,body,search_tokens,canonical_key,state,revision,supersedes_id,valid_from_ms,source_watermark,created_ms,updated_ms) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ident,
            owner,
            kind,
            project_id,
            conversation_id,
            task_id,
            day_key,
            timezone,
            title,
            body,
            search_tokens(title + " " + body),
            key,
            state,
            max([item["revision"] for item in existing], default=0) + 1,
            active["id"] if active else None,
            timestamp,
            source_watermark,
            timestamp,
            timestamp,
        ),
    )
    for source in sources:
        db.execute(
            "INSERT INTO memory_sources(memory_id,source_key,message_id,event_id,artifact_id,source_sha256) VALUES(?,?,?,?,?,?)",
            (
                ident,
                source["id"],
                source["message_id"],
                source["event_id"],
                source.get("artifact_id"),
                source["sha256"],
            ),
        )
    if confirmed:
        db.execute(
            "UPDATE owner_versions SET memory_epoch=memory_epoch+1 WHERE owner_id=?", (owner,)
        )
    return row(db, "SELECT * FROM memory_records WHERE id=?", (ident,))
