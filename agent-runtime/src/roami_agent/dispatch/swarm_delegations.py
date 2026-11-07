"""Explicit current-user delegation for a project's original Main and selected roles."""

import json

from roami_agent.conversation.okr_message_context import human_text
from roami_agent.dispatch.task_sessions import assert_session_open
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row
from roami_agent.storage.request_quotes import MAX_QUOTE_LENGTH, source_quote
from roami_agent.storage.swarm_delegations import (
    current_delegation,
    source_digest,
    source_messages,
    user_source,
)
from roami_agent.storage.swarm_repository import changed, group, receipt
from roami_agent.storage.swarm_scopes import require_scope


class SwarmDelegations:
    def __init__(self, database):
        self.db = database

    @staticmethod
    def _source(db, owner, team, binding):
        if (
            not isinstance(binding, dict)
            or binding.get("taskId")
            or binding.get("conversation") != team["conversation_id"]
        ):
            raise DomainError("SWARM_MAIN_REQUIRED", 403)
        turn = row(
            db,
            "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id "
            "WHERE t.id=? AND t.conversation_id=? AND c.owner_id=? AND t.trigger_kind='user' "
            "AND t.state='running' AND t.branch_id=c.active_branch_id AND c.deleted_ms IS NULL",
            (binding.get("turnId"), team["conversation_id"], owner),
        )
        lease = binding.get("leaseEpoch")
        if (
            not turn
            or lease is not None
            and (type(lease) is not int or lease != turn["lease_epoch"])
        ):
            raise DomainError("SWARM_DELEGATION_USER_REQUEST_REQUIRED", 409)
        message = row(
            db,
            "SELECT id FROM messages WHERE turn_id=? AND role='user' ORDER BY seq LIMIT 1",
            (turn["id"],),
        )
        source = user_source(db, owner, team["conversation_id"], message["id"]) if message else None
        if not source:
            raise DomainError("SWARM_DELEGATION_USER_REQUEST_REQUIRED", 409)
        assert_context_admitted(db, turn)
        return turn, source

    async def enable(self, owner, swarm_id, spec, *, binding):
        members, quote, expected = (
            spec.get("memberIds"),
            spec.get("sourceQuote"),
            spec.get("expectedDelegationRevision"),
        )
        if (
            not isinstance(members, list)
            or not members
            or len(members) > 100
            or any(not isinstance(value, str) or not value for value in members)
            or len(set(members)) != len(members)
            or not isinstance(quote, str)
            or not quote.strip()
            or len(quote) > MAX_QUOTE_LENGTH
            or type(expected) is not int
            or expected < 0
        ):
            raise DomainError("INVALID_SWARM_DELEGATION")

        def write(db):
            team = group(db, owner, swarm_id)
            require_scope(team)
            if team["scope_project_id"] is None:
                raise DomainError("SWARM_PROJECT_REQUIRED", 409)
            if team["paused"] or team["archived"]:
                raise DomainError("SWARM_COORDINATION_PAUSED", 409)
            turn, source = self._source(db, owner, team, binding)
            actual_quote = source_quote(human_text(json.loads(source["body"])), quote)
            if actual_quote is None:
                raise DomainError("SWARM_DELEGATION_SOURCE_REQUIRED", 409)

            def apply():
                previous = (
                    row(
                        db,
                        "SELECT max(revision) AS revision FROM swarm_goal_delegations WHERE swarm_id=?",
                        (swarm_id,),
                    )["revision"]
                    or 0
                )
                if previous != expected:
                    raise DomainError("SWARM_DELEGATION_REVISION_CHANGED", 409)
                for member_id in members:
                    member = row(
                        db,
                        "SELECT m.id,w.task_id FROM swarm_members m LEFT JOIN swarm_work_items w ON w.id=m.current_work_id WHERE m.swarm_id=? AND m.id=?",
                        (swarm_id, member_id),
                    )
                    if not member:
                        raise DomainError("SWARM_MEMBER_REQUIRED", 403)
                    if member["task_id"]:
                        assert_session_open(db, member["task_id"])
                stamp = now_ms()
                db.execute(
                    "UPDATE swarm_goal_delegations SET revoked_ms=?,revoked_by_message_id=? WHERE swarm_id=? AND revoked_ms IS NULL",
                    (stamp, source["id"], swarm_id),
                )
                delegation_id = identity()
                db.execute(
                    "INSERT INTO swarm_goal_delegations(id,swarm_id,revision,source_message_id,source_quote,source_sha256,source_messages_json,member_ids_json,created_ms) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        delegation_id,
                        swarm_id,
                        previous + 1,
                        source["id"],
                        actual_quote,
                        source_digest(source["body"]),
                        encoded(source_messages(db, turn, source)),
                        encoded(members),
                        stamp,
                    ),
                )
                changed(db, team, "swarm.delegation.changed")
                return {
                    "delegationId": delegation_id,
                    "revision": previous + 1,
                    "sourceMessageId": source["id"],
                    "memberIds": members,
                }

            return receipt(
                db,
                owner,
                spec["commandKey"],
                {"swarmId": swarm_id, **spec, "sourceTurnId": turn["id"]},
                apply,
                swarm_id=swarm_id,
            )

        return await self.db.call(write, write=True)

    async def revoke(self, owner, swarm_id, spec, *, binding):
        expected = spec.get("expectedDelegationRevision")
        if type(expected) is not int or expected < 1:
            raise DomainError("INVALID_SWARM_DELEGATION")

        def write(db):
            team = group(db, owner, swarm_id)
            turn, source = self._source(db, owner, team, binding)

            def apply():
                value = row(
                    db,
                    "SELECT * FROM swarm_goal_delegations WHERE swarm_id=? ORDER BY revision DESC LIMIT 1",
                    (swarm_id,),
                )
                if not value or value["revision"] != expected:
                    raise DomainError("SWARM_DELEGATION_REVISION_CHANGED", 409)
                if value["revoked_ms"] is None:
                    db.execute(
                        "UPDATE swarm_goal_delegations SET revoked_ms=?,revoked_by_message_id=? WHERE id=?",
                        (now_ms(), source["id"], value["id"]),
                    )
                    changed(db, team, "swarm.delegation.changed")
                return {"delegationId": value["id"], "revision": value["revision"], "revoked": True}

            return receipt(
                db,
                owner,
                spec["commandKey"],
                {"swarmId": swarm_id, **spec, "sourceTurnId": turn["id"]},
                apply,
                swarm_id=swarm_id,
            )

        return await self.db.call(write, write=True)

    async def current(self, owner, swarm_id, delegation_id=None):
        return await self.db.call(lambda db: current_delegation(db, owner, swarm_id, delegation_id))
