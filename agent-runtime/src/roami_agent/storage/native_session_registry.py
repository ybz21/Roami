"""Host-generated identities for persistent native task conversations."""

import json
import secrets
import sqlite3
from datetime import UTC, datetime

from roami_agent.protocol.identity import now_ms
from roami_agent.storage.database import row, rows
from roami_agent.storage.native_public_record import public_value


def register(db, task_id, conversation_id, branch_id):
    prior = row(db, "SELECT * FROM native_sessions WHERE task_id=?", (task_id,))
    if prior:
        return prior
    task = row(db, "SELECT * FROM tasks WHERE id=?", (task_id,))
    parent = row(db, "SELECT * FROM native_sessions WHERE task_id=?", (task["parent_task_id"],))
    created = task["created_ms"]
    stamp = datetime.fromtimestamp(created / 1000, UTC).strftime("%Y%m%dT%H%M%S")
    for attempt in range(10):
        ident = f"{stamp}{created % 1000:03d}Z-{secrets.token_hex(6)}"
        try:
            db.execute(
                "INSERT INTO native_sessions(id,task_id,conversation_id,branch_id,owner_id,parent_session_id,parent_conversation_id,root_conversation_id,created_ms) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    ident,
                    task_id,
                    conversation_id,
                    branch_id,
                    task["owner_id"],
                    parent["id"] if parent else None,
                    task["origin_conversation_id"],
                    parent["root_conversation_id"] if parent else task["origin_conversation_id"],
                    created,
                ),
            )
            break
        except sqlite3.IntegrityError:
            if attempt == 9 or not row(db, "SELECT id FROM native_sessions WHERE id=?", (ident,)):
                raise
    append(
        db,
        ident,
        "session.created",
        ident,
        {"taskId": task_id, "conversationId": conversation_id, "branchId": branch_id},
    )
    return row(db, "SELECT * FROM native_sessions WHERE id=?", (ident,))


def append(db, session_id, kind, entity_id, payload):
    seq = db.execute(
        "UPDATE native_sessions SET last_seq=last_seq+1 WHERE id=? RETURNING last_seq",
        (session_id,),
    ).fetchone()[0]
    db.execute(
        "INSERT INTO native_session_events(session_id,seq,event_id,kind,entity_id,payload_json,created_ms) VALUES(?,?,?,?,?,?,?)",
        (
            session_id,
            seq,
            secrets.token_hex(16),
            kind,
            entity_id,
            json.dumps(payload, ensure_ascii=False),
            now_ms(),
        ),
    )


def backfill(db):
    for entry in rows(
        db,
        "SELECT t.id,b.id AS branch_id,b.conversation_id FROM tasks t JOIN task_attempts a ON a.task_id=t.id JOIN branches b ON b.id=a.native_branch_id WHERE NOT EXISTS(SELECT 1 FROM native_sessions n WHERE n.task_id=t.id) GROUP BY t.id HAVING COUNT(DISTINCT b.id)=1 ORDER BY t.rowid",
    ):
        session = register(db, entry["id"], entry["conversation_id"], entry["branch_id"])
        for message in rows(
            db,
            "SELECT * FROM messages WHERE conversation_id=? AND branch_id=? AND status NOT IN ('pending','streaming','deleted') AND deleted_ms IS NULL ORDER BY seq",
            (entry["conversation_id"], entry["branch_id"]),
        ):
            append(
                db,
                session["id"],
                "message.committed",
                message["id"],
                {
                    "messageId": message["id"],
                    "role": message["role"],
                    "content": public_value(json.loads(message["content_json"])),
                    "turnId": message["turn_id"],
                    "status": message["status"],
                    "backfilled": True,
                    "originalCreatedMs": message["created_ms"],
                },
            )

        for call in rows(
            db,
            "SELECT x.* FROM tool_calls x JOIN turns u ON u.id=x.turn_id WHERE u.branch_id=? ORDER BY x.created_ms,x.rowid",
            (entry["branch_id"],),
        ):
            append(
                db,
                session["id"],
                "tool." + call["state"],
                call["id"],
                public_value(
                    {
                        "callId": call["id"],
                        "turnId": call["turn_id"],
                        "toolName": call["tool_name"],
                        "arguments": json.loads(call["arguments_json"]),
                        "state": call["state"],
                        "effect": call["effect"],
                        "resultMessageId": call["result_message_id"],
                    }
                ),
            )
