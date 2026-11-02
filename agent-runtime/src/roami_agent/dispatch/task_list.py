"""The Web task list never materializes instructions, budgets or attempt reports."""

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row, rows
from roami_agent.storage.transcript_repository import owned


def task_page(db, owner, cid, *, before=None, limit=20, state_filter="all"):
    if cid:
        owned(db, owner, cid)
    filters = {
        "all": "1",
        "active": "state IN ('queued','preparing','running','verifying','cancelling') AND NOT uncertain",
        "attention": "uncertain OR state NOT IN ('queued','preparing','running','verifying','cancelling','succeeded','cancelled')",
        "ended": "state IN ('succeeded','failed','cancelled','interrupted')",
        "open": "closure_state IS NOT 'closed' AND (native_id IS NOT NULL OR agent_conversation_id IS NOT NULL OR (session_id IS NOT NULL AND state NOT IN ('succeeded','failed','cancelled','interrupted')))",
    }
    if state_filter not in filters:
        raise DomainError("INVALID_TASK_FILTER")
    cursor = None
    if before:
        cursor = row(
            db,
            "SELECT id,created_ms FROM tasks WHERE id=? AND owner_id=? "
            + ("AND origin_conversation_id=?" if cid else ""),
            (before, owner, *((cid,) if cid else ())),
        )
        if not cursor:
            raise DomainError("INVALID_TASK_CURSOR")
    query = """
        WITH candidates AS (
          SELECT t.id,t.state,t.revision,t.parent_task_id,t.created_ms,t.updated_ms,
            substr(COALESCE(json_extract(t.intent_json,'$.initialIntent.title'),
              json_extract(t.intent_json,'$.title'),json_extract(t.intent_json,'$.initialIntent.goal'),
              json_extract(t.intent_json,'$.goal'),''),1,120) AS title,
            json_extract(t.intent_json,'$.executor') AS executor,
            COALESCE(json_extract(t.target_json,'$.projectId'),json_extract(t.intent_json,'$.target.projectId')) AS project_id,
            n.id AS native_id,n.conversation_id AS native_conversation,
            c.state AS closure_state,a.state AS attempt_state,a.executor_kind,
            a.session_id,a.agent_conversation_id,
            (t.state IN ('running','preparing') AND COALESCE(a.state='unknown',0)) AS uncertain
          FROM tasks t
          JOIN conversations origin ON origin.id=t.origin_conversation_id AND origin.owner_id=t.owner_id AND origin.deleted_ms IS NULL
          JOIN messages source ON source.id=t.origin_message_id AND source.deleted_ms IS NULL AND source.status!='deleted'
          LEFT JOIN task_attempts a ON a.id=(SELECT id FROM task_attempts WHERE task_id=t.id ORDER BY attempt_no DESC LIMIT 1)
          LEFT JOIN native_sessions n ON n.task_id=t.id
          LEFT JOIN task_session_closures c ON c.task_id=t.id
          WHERE t.owner_id=?
    """
    args = [owner]
    if cid:
        query += " AND t.origin_conversation_id=?"
        args.append(cid)
    query += " AND NOT EXISTS (SELECT 1 FROM tasks p WHERE p.id=t.parent_task_id AND p.owner_id=t.owner_id AND p.origin_conversation_id=t.origin_conversation_id)"
    query += " AND NOT EXISTS (SELECT 1 FROM context_omissions o WHERE o.owner_id=t.owner_id AND o.message_id=t.origin_message_id)"
    if cursor:
        query += " AND (t.created_ms<? OR (t.created_ms=? AND t.id<?))"
        args.extend([cursor["created_ms"], cursor["created_ms"], cursor["id"]])
    query += (
        ") SELECT * FROM candidates WHERE ("
        + filters[state_filter]
        + ") ORDER BY created_ms DESC,id DESC LIMIT ?"
    )
    found = rows(db, query, (*args, limit + 1))
    items = []
    for value in found[:limit]:
        items.append(
            {
                **{
                    key: value[key]
                    for key in (
                        "id",
                        "state",
                        "revision",
                        "parent_task_id",
                        "created_ms",
                        "updated_ms",
                        "title",
                        "executor",
                    )
                },
                "projectId": value["project_id"],
                "nativeSession": {
                    "id": value["native_id"],
                    "conversationId": value["native_conversation"],
                }
                if value["native_id"]
                else None,
                "sessionClosure": {"state": value["closure_state"]}
                if value["closure_state"]
                else None,
                "latestAttempt": {
                    "state": value["attempt_state"],
                    "executorKind": value["executor_kind"],
                    "sessionId": value["session_id"],
                    "agentConversationId": value["agent_conversation_id"],
                }
                if value["attempt_state"]
                else None,
            }
        )
    return {"items": items, "nextCursor": items[-1]["id"] if len(found) > limit else None}
