"""Keep in-flight forgotten context from starting another model or tool operation."""

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row


def assert_context_admitted(db, turn):
    if row(
        db,
        "SELECT 1 FROM context_omissions o WHERE o.owner_id=? AND ("
        "o.message_id IN (SELECT id FROM messages WHERE turn_id=?) OR "
        "o.message_id IN (SELECT j.value FROM prompt_manifests p JOIN json_each(p.parts_json,'$.sourceMessageIds') j WHERE p.turn_id=?)) LIMIT 1",
        (turn["owner_id"], turn["id"], turn["id"]),
    ):
        raise DomainError("CONTEXT_SOURCE_FORGOTTEN", 409)
