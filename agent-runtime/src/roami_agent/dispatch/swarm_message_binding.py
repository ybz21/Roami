"""Current managed identities for group message delivery and retrieval."""

from roami_agent.dispatch.task_sessions import assert_session_open
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row


def bound_member(db, group, binding):
    if not isinstance(binding, dict) or not binding:
        raise DomainError("SWARM_MAIN_REQUIRED", 403)
    if not binding.get("taskId"):
        if binding.get("conversation") != group["conversation_id"]:
            raise DomainError("SWARM_MAIN_REQUIRED", 403)
        if "turnId" in binding:
            turn = row(
                db,
                "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id "
                "WHERE t.id=? AND t.conversation_id=? AND c.owner_id=? AND c.deleted_ms IS NULL "
                "AND t.branch_id=c.active_branch_id AND t.state='running'",
                (binding["turnId"], group["conversation_id"], group["owner_id"]),
            )
            if (
                not turn
                or "leaseEpoch" in binding
                and (
                    type(binding["leaseEpoch"]) is not int
                    or binding["leaseEpoch"] != turn["lease_epoch"]
                )
            ):
                raise DomainError("SWARM_MAIN_TURN_REQUIRED", 409)
            assert_context_admitted(db, turn)
        return None
    member = row(
        db,
        "SELECT m.id,m.name FROM swarm_members m JOIN swarm_work_items w ON w.id=m.current_work_id "
        "WHERE m.swarm_id=? AND w.task_id=?",
        (group["id"], binding["taskId"]),
    )
    if not member:
        raise DomainError("SWARM_MEMBER_REQUIRED", 403)
    task = row(db, "SELECT revision,state FROM tasks WHERE id=?", (binding["taskId"],))
    attempt = row(
        db,
        "SELECT id FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
        (binding["taskId"], task["revision"]),
    )
    if (
        not attempt
        or attempt["id"] != binding.get("runId")
        or binding.get("taskRevision") is not None
        and binding["taskRevision"] != task["revision"]
        or task["state"] not in {"queued", "preparing", "running", "verifying", "waiting_user"}
    ):
        raise DomainError("TASK_RESULT_SUPERSEDED", 409)
    assert_session_open(db, binding["taskId"])
    return member
