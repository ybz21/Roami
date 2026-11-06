"""Provisional reply metadata never becomes model input or terminal history."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row


def clear_reply_previews(db, turn_id):
    db.execute(
        "UPDATE messages SET content_json=json_remove(content_json,'$.replyPreview') "
        "WHERE turn_id=? AND json_type(content_json,'$.replyPreview') IS NOT NULL",
        (turn_id,),
    )


def assert_preview_current(db, turn, mid, *, clearing=False):
    current = row(
        db,
        "SELECT t.lease_epoch FROM turns t JOIN conversations c ON c.id=t.conversation_id "
        "JOIN messages m ON m.turn_id=t.id WHERE t.id=? AND c.id=? AND c.owner_id=? "
        "AND c.deleted_ms IS NULL AND c.active_branch_id=t.branch_id AND t.state='running' "
        "AND m.id=? AND m.deleted_ms IS NULL AND (m.status='streaming' OR (? AND m.status='completed'))",
        (turn["id"], turn["conversation_id"], turn["owner_id"], mid, clearing),
    )
    if not current or current["lease_epoch"] != turn.get("lease_epoch", current["lease_epoch"]):
        raise DomainError("TURN_INTERRUPTED", 409)
    return current["lease_epoch"]


def preview_visible(db, mid):
    current = row(
        db,
        "SELECT t.id,c.owner_id FROM messages m JOIN turns t ON t.id=m.turn_id "
        "JOIN conversations c ON c.id=m.conversation_id WHERE m.id=? "
        "AND m.deleted_ms IS NULL AND m.status IN ('streaming','completed') "
        "AND t.state='running' AND c.deleted_ms IS NULL AND c.active_branch_id=m.branch_id "
        "AND t.lease_epoch=json_extract(m.content_json,'$.replyPreview.leaseEpoch') "
        "AND NOT EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=c.owner_id AND o.message_id=m.id)",
        (mid,),
    )

    if current:
        try:
            assert_context_admitted(db, current)
        except DomainError:
            return None
    return current


def public_preview_message(db, value):
    content = json.loads(value["content_json"])
    if "replyPreview" not in content:
        return value
    if preview_visible(db, value["id"]):
        content["replyPreview"].pop("leaseEpoch", None)
    else:
        content.pop("replyPreview")
    return dict(value, content_json=encoded(content))
