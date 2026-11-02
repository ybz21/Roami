"""Notification badges and pages share visibility without fetching full message bodies."""

from roami_agent.protocol.identity import now_ms
from roami_agent.storage.database import rows

NOTICE_FROM = (
    " FROM events e JOIN conversations c ON c.id=e.conversation_id "
    "JOIN messages m ON m.id=e.message_id LEFT JOIN conversation_reads r "
    "ON r.conversation_id=c.id AND r.owner_id=c.owner_id WHERE c.owner_id=? "
    "AND c.deleted_ms IS NULL AND m.deleted_ms IS NULL AND m.status!='deleted' "
    "AND e.kind='message.completed' AND NOT EXISTS "
    "(SELECT 1 FROM task_attempts a JOIN branches b ON b.id=a.native_branch_id WHERE b.conversation_id=c.id) "
    "AND NOT EXISTS (SELECT 1 FROM context_omissions o WHERE o.owner_id=c.owner_id AND o.message_id=m.id) "
)


def notification_summary(db, owner):
    return dict(
        db.execute(
            "SELECT COALESCE(SUM(e.id>COALESCE(r.event_cursor,0)),0) AS unread,COALESCE(MAX(e.id),0) AS cursor"
            + NOTICE_FROM,
            (owner,),
        ).fetchone()
    )


def notification_page(db, owner, *, before=None, limit=20, unread_only=False):
    query = (
        "SELECT e.id,e.conversation_id,e.message_id,m.branch_id,e.created_ms,substr(c.title,1,200) AS title,"
        "substr(json_extract(native_content(m.content_json),'$.text'),1,180) AS summary,"
        "(e.id<=COALESCE(r.event_cursor,0)) AS read" + NOTICE_FROM
    )
    args = [owner]
    if unread_only:
        query += " AND e.id>COALESCE(r.event_cursor,0)"
    if before is not None:
        query += " AND e.id<?"
        args.append(before)
    found = rows(db, query + " ORDER BY e.id DESC LIMIT ?", (*args, limit + 1))
    items = found[:limit]
    return {"items": items, "nextCursor": str(items[-1]["id"]) if len(found) > limit else None}


def mark_notifications_read(db, owner, cursor):
    db.execute(
        "INSERT INTO conversation_reads(owner_id,conversation_id,event_cursor,updated_ms) "
        "SELECT ?,e.conversation_id,MAX(e.id),?"
        + NOTICE_FROM
        + " AND e.id<=? GROUP BY e.conversation_id "
        "ON CONFLICT(owner_id,conversation_id) DO UPDATE SET "
        "event_cursor=MAX(conversation_reads.event_cursor,excluded.event_cursor),updated_ms=excluded.updated_ms",
        (owner, now_ms(), owner, cursor),
    )
    return notification_summary(db, owner)
