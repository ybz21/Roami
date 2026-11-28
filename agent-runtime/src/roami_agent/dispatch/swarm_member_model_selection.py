"""Change the model of a stopped Swarm member's current native session."""

import hashlib
import json
import logging

from roami_agent.dispatch.native_model_selection import (
    BEFORE_INPUT,
    claim_model_selection,
    model_selection_still_claimed,
    select_bound_model,
)
from roami_agent.dispatch.swarm_member_stop import require_stopped_member_task
from roami_agent.dispatch.task_sessions import assert_session_open
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row
from roami_agent.storage.swarm_members import MEMBER_MODEL_JOB, pending_member_model_selection
from roami_agent.storage.swarm_repository import changed, group
from roami_agent.storage.swarm_scopes import require_scope

log = logging.getLogger(__name__)


def selection_status(job):
    value = json.loads(job["payload_json"])
    spec = value["request"]
    return {
        "commandKey": spec["commandKey"],
        "memberId": value["memberId"],
        "taskId": spec["taskId"],
        "model": spec["model"],
        "state": {"queued": "pending", "done": "applied", "failed": "rejected"}[job["state"]],
        **({"reason": value["reason"]} if value.get("reason") else {}),
    }


class MemberModelSelections:
    def __init__(self, database, executor, wakeup):
        self.db, self.executor, self.wakeup = database, executor, wakeup

    async def request(self, owner, sid, member_id, spec):
        if not spec["commandKey"].strip() or spec["expectedModel"] == spec["model"]:
            raise DomainError("INVALID_SESSION_MODEL_SELECTION")
        if not callable(getattr(self.executor, "command", None)):
            raise DomainError("SWARM_MEMBER_MODEL_SELECTION_UNAVAILABLE", 409)
        digest = hashlib.sha256(encoded([owner, sid, member_id, spec["commandKey"]]).encode())
        native_key = "member-model:" + digest.hexdigest()

        def write(db):
            team = group(db, owner, sid)
            require_scope(team)
            prior = row(db, "SELECT * FROM jobs WHERE dedupe_key=?", (native_key,))
            if prior:
                if json.loads(prior["payload_json"])["request"] != spec:
                    raise DomainError("REQUEST_KEY_CONFLICT", 409)
                return selection_status(prior)
            if pending_member_model_selection(db, spec["taskId"]):
                raise DomainError("SWARM_MEMBER_MODEL_SELECTION_PENDING", 409)
            _, work, provider = self.binding(db, owner, sid, member_id, spec)
            value = {
                "owner": owner,
                "swarmId": sid,
                "memberId": member_id,
                "workId": work["id"],
                "launchKey": provider["launch_key"],
                "request": spec,
            }
            jid = identity()
            db.execute(
                "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) "
                "VALUES(?,?,?,?,?,'queued',?)",
                (jid, MEMBER_MODEL_JOB, spec["taskId"], native_key, encoded(value), now_ms()),
            )
            return selection_status(row(db, "SELECT * FROM jobs WHERE id=?", (jid,)))

        result = await self.db.call(write, write=True)
        self.wakeup.set()
        return result

    @staticmethod
    def binding(db, owner, sid, member_id, spec, own_job=None, *, unsubmitted_run=None):
        team = group(db, owner, sid)
        require_scope(team)
        member = row(db, "SELECT * FROM swarm_members WHERE id=? AND swarm_id=?", (member_id, sid))
        if not member:
            raise DomainError("SWARM_MEMBER_NOT_FOUND", 404)
        if member["executor"] != "claude" or member["retired_ms"] is not None or team["archived"]:
            raise DomainError("SWARM_MEMBER_MODEL_SELECTION_UNAVAILABLE", 409)
        if (
            member["execution_generation"] != spec["expectedGeneration"]
            or member["model"] != spec["expectedModel"]
        ):
            raise DomainError("SWARM_MEMBER_MODEL_BINDING_CHANGED", 409)
        work = row(
            db,
            "SELECT w.* FROM swarm_work_items w JOIN swarm_member_work b ON b.work_id=w.id "
            "WHERE w.id=? AND w.swarm_id=? AND b.member_id=? AND w.task_id=? AND w.execution_generation=? "
            "AND w.executor='claude' AND w.model=?",
            (
                member["current_work_id"],
                sid,
                member_id,
                spec["taskId"],
                spec["expectedGeneration"],
                spec["expectedModel"],
            ),
        )
        task = row(db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (spec["taskId"], owner))
        if not work or not task or task["revision"] != spec["expectedTaskRevision"]:
            raise DomainError("SWARM_MEMBER_MODEL_BINDING_CHANGED", 409)
        assert_session_open(db, task["id"])
        require_stopped_member_task(
            db,
            owner,
            team,
            task,
            allow_waiting_review=True,
            own_job=own_job,
            unsubmitted_run=unsubmitted_run,
        )
        provider = row(
            db,
            "SELECT p.* FROM swarm_member_provider_generations p "
            "JOIN task_attempts a ON a.task_id=? AND a.task_revision=? AND a.id=? "
            "AND (a.session_id=p.session_id AND a.agent_conversation_id=p.provider_id OR a.id=?) "
            "WHERE p.member_id=? AND p.generation=? AND p.owner_id=? AND p.swarm_id=? "
            "AND p.executor='claude' AND p.model=? AND a.executor_kind='cli' "
            "AND NOT EXISTS(SELECT 1 FROM task_attempts n WHERE n.task_id=a.task_id AND n.attempt_no>a.attempt_no)",
            (
                task["id"],
                task["revision"],
                spec["expectedRunId"],
                unsubmitted_run,
                member_id,
                spec["expectedGeneration"],
                owner,
                sid,
                spec["expectedModel"],
            ),
        )
        if not provider:
            raise DomainError("SWARM_MEMBER_MODEL_BINDING_CHANGED", 409)
        return team, work, provider

    def current(self, db, operation, value):
        team, work, provider = self.binding(
            db,
            value["owner"],
            value["swarmId"],
            value["memberId"],
            value["request"],
            operation["id"],
        )
        if provider["launch_key"] != value["launchKey"] or work["id"] != value["workId"]:
            raise DomainError("SWARM_MEMBER_MODEL_BINDING_CHANGED", 409)
        return team, provider

    async def advance(self, job):
        operation = await self.db.call(
            lambda db: claim_model_selection(db, job["id"], MEMBER_MODEL_JOB), write=True
        )
        if not operation:
            return
        value = json.loads(operation["payload_json"])
        spec = value["request"]
        request = {
            "key": operation["dedupe_key"],
            "preparedFrom": value["launchKey"],
            "expectedModel": spec["expectedModel"],
            "model": spec["model"],
            **({"allowMetered": True} if spec.get("allowMetered") else {}),
        }
        before_input = True
        try:
            _, previous = await self.db.call(lambda db: self.current(db, operation, value))
            before_input = False
            selected = await select_bound_model(
                self.executor.command, previous, request, "SWARM_MEMBER_MODEL_SELECTION_UNCONFIRMED"
            )
            await self.db.call(
                lambda db: self.finish(db, operation, value, previous, selected), write=True
            )
            self.wakeup.set()
        except (DomainError, OSError, TimeoutError) as error:
            code = getattr(error, "code", "CODING_EXECUTOR_UNAVAILABLE")
            log.debug("Swarm member model selection is unsettled: %s", code)
            rejected = code in BEFORE_INPUT or before_input and operation["attempts"] == 0
            await self.db.call(
                lambda db: self.save_status(db, operation, value, code, rejected), write=True
            )
            self.wakeup.set()

    def finish(self, db, operation, value, previous, selected):
        if not model_selection_still_claimed(db, operation):
            return
        team, provider = self.current(db, operation, value)
        if provider != previous:
            raise DomainError("SWARM_MEMBER_MODEL_BINDING_CHANGED", 409)
        model = selected["model"]
        db.execute("UPDATE swarm_members SET model=? WHERE id=?", (model, value["memberId"]))
        db.execute("UPDATE swarm_work_items SET model=? WHERE id=?", (model, value["workId"]))
        db.execute(
            "UPDATE swarm_member_provider_generations SET model=? WHERE launch_key=?",
            (model, provider["launch_key"]),
        )
        value.pop("reason", None)
        value["proofSha256"] = selected["proof"]["sourceSha256"]
        db.execute(
            "UPDATE jobs SET state='done',payload_json=? WHERE id=?",
            (encoded(value), operation["id"]),
        )
        db.execute("UPDATE swarm_groups SET revision=revision+1 WHERE id=?", (team["id"],))
        team["revision"] += 1
        changed(db, team, "swarm.member_model_changed")

    def save_status(self, db, operation, value, code, rejected):
        if model_selection_still_claimed(db, operation):
            value["reason"] = code
            db.execute(
                "UPDATE jobs SET state=?,payload_json=? WHERE id=?",
                ("failed" if rejected else "queued", encoded(value), operation["id"]),
            )
