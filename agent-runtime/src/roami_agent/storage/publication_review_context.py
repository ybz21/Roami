"""The independent Main's current admitted review, before its decision is frozen."""

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row


def review_turn(db, binding):
    if (
        binding.get("role") != "main"
        or binding.get("taskId")
        or type(binding.get("leaseEpoch")) is not int
    ):
        raise DomainError("PUBLICATION_MAIN_REQUIRED", 403)
    turn = row(
        db,
        "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id "
        "JOIN messages current ON current.id=? AND current.turn_id=t.id AND current.role='assistant' "
        "AND current.conversation_id=t.conversation_id AND current.branch_id=t.branch_id "
        "AND current.deleted_ms IS NULL AND current.status!='deleted' "
        "WHERE t.id=? AND t.conversation_id=? AND c.owner_id=? AND c.deleted_ms IS NULL "
        "AND t.state='running' AND t.branch_id=c.active_branch_id AND t.lease_epoch=?",
        (
            binding.get("assistantMessageId"),
            binding.get("turnId"),
            binding.get("conversation"),
            binding.get("owner"),
            binding["leaseEpoch"],
        ),
    )
    if not turn:
        raise DomainError("PUBLICATION_MAIN_REQUIRED", 403)
    assert_context_admitted(db, turn)
    return turn
