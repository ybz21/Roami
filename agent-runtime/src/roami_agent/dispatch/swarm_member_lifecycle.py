"""Change the current roster without discarding a member's execution history."""

from roami_agent.dispatch.swarm_member_stop import require_stopped_member_task
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.storage.database import row, rows
from roami_agent.storage.swarm_repository import changed, group, receipt


def change_members(db, owner, sid, spec):
    from roami_agent.dispatch.swarm_plans import SwarmPlans

    action, ids = spec.get("action"), spec.get("memberIds")
    if (
        action not in ("retire", "restore")
        or not isinstance(ids, list)
        or not 1 <= len(ids) <= 100
        or any(not isinstance(ident, str) or not ident.strip() or len(ident) > 200 for ident in ids)
        or len(ids) != len(set(ids))
    ):
        raise DomainError("INVALID_SWARM_MEMBER_LIFECYCLE")

    def apply():
        team = group(db, owner, sid)
        SwarmPlans.mutable(team, spec)
        members = []
        retire = action == "retire"
        stamp = now_ms() if retire else None
        updated = False
        for ident in ids:
            member = row(db, "SELECT * FROM swarm_members WHERE swarm_id=? AND id=?", (sid, ident))
            if not member:
                raise DomainError("SWARM_MEMBER_NOT_FOUND", 404)
            if (member["retired_ms"] is not None) != retire:
                if retire:
                    require_retirement_ready(db, owner, team, member)
                db.execute("UPDATE swarm_members SET retired_ms=? WHERE id=?", (stamp, ident))
                member["retired_ms"] = stamp
                updated = True
            members.append(
                {"id": ident, "name": member["name"], "retiredAtMs": member["retired_ms"]}
            )
        if updated:
            db.execute("UPDATE swarm_groups SET revision=revision+1 WHERE id=?", (sid,))
            team["revision"] += 1
            changed(db, team, "swarm.members_changed")
        return {"id": sid, "revision": team["revision"], "members": members}

    return receipt(db, owner, spec.get("commandKey"), {"swarmId": sid, **spec}, apply, swarm_id=sid)


def require_retirement_ready(db, owner, team, member):
    if row(
        db,
        "SELECT 1 FROM swarm_goal_delegations d, json_each(d.member_ids_json) m "
        "WHERE d.swarm_id=? AND d.revoked_ms IS NULL AND m.value=? LIMIT 1",
        (team["id"], member["id"]),
    ):
        raise DomainError("SWARM_MEMBER_DELEGATION_ACTIVE", 409)
    if row(
        db,
        "SELECT 1 FROM swarm_member_work b JOIN swarm_work_items w ON b.work_id=w.id "
        "WHERE b.member_id=? AND w.task_id IS NULL AND w.dispatch_error IS NULL LIMIT 1",
        (member["id"],),
    ):
        raise DomainError("SWARM_MEMBER_STOP_REQUIRED", 409)
    for task in rows(
        db,
        "SELECT t.* FROM tasks t WHERE t.id IN ("
        "SELECT w.task_id FROM swarm_member_work b JOIN swarm_work_items w ON b.work_id=w.id "
        "WHERE b.member_id=? UNION SELECT task_id FROM swarm_member_rounds WHERE member_id=?)",
        (member["id"], member["id"]),
    ):
        require_stopped_member_task(db, owner, team, task, allow_settled_native=True)
