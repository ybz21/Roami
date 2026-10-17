from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row, rows


def owned(db, owner: str, conversation_id: str):
    result = row(
        db,
        "SELECT * FROM conversations WHERE id=? AND owner_id=? AND deleted_ms IS NULL",
        (conversation_id, owner),
    )
    if not result:
        raise DomainError("CONVERSATION_NOT_FOUND", 404)
    return result


def message(
    db,
    conversation_id,
    branch_id,
    role,
    content,
    *,
    turn_id=None,
    status="completed",
    message_id=None,
):
    seq = db.execute(
        "UPDATE branches SET head_seq=head_seq+1 WHERE id=? RETURNING head_seq", (branch_id,)
    ).fetchone()[0]
    ident = message_id or identity()
    db.execute(
        "INSERT INTO messages(id,conversation_id,branch_id,seq,turn_id,role,content_json,"
        "status,created_ms) VALUES(?,?,?,?,?,?,?,?,?)",
        (ident, conversation_id, branch_id, seq, turn_id, role, encoded(content), status, now_ms()),
    )
    db.execute("UPDATE conversations SET updated_ms=? WHERE id=?", (now_ms(), conversation_id))
    return ident


def history(db, branch_id, *, through=None, depth=0):
    if depth > 16:
        raise DomainError("BRANCH_DEPTH_EXCEEDED")
    branch = row(db, "SELECT * FROM branches WHERE id=?", (branch_id,))
    if not branch:
        raise DomainError("BRANCH_NOT_FOUND", 404)
    prefix = []
    if branch["parent_branch_id"]:
        cut = row(db, "SELECT seq FROM messages WHERE id=?", (branch["fork_message_id"],))
        prefix = history(db, branch["parent_branch_id"], through=cut["seq"], depth=depth + 1)
    suffix = rows(
        db,
        "SELECT * FROM messages WHERE branch_id=? AND seq<=? AND deleted_ms IS NULL "
        "AND status!='deleted' ORDER BY seq",
        (branch_id, branch["head_seq"] if through is None else through),
    )
    return prefix + suffix
