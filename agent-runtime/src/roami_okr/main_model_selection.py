"""Coordinate a confirmed native model change with the original project Main queue."""

import hashlib
import json
import logging

from roami_agent.conversation.idle import assert_main_idle
from roami_agent.dispatch.native_model_selection import (
    BEFORE_INPUT,
    claim_model_selection,
    model_selection_still_claimed,
    select_bound_model,
)
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import event, row
from roami_agent.storage.transcript_repository import owned
from roami_okr.intake import assert_project_main

log = logging.getLogger(__name__)
JOB_KIND = "project.main.select_model"


def pending_model_selection(db, cid):
    return row(
        db, "SELECT * FROM jobs WHERE kind=? AND aggregate_id=? AND state='queued'", (JOB_KIND, cid)
    )


def main_model_selection_status(job):
    value = json.loads(job["payload_json"])
    result = {
        "commandKey": value["request"]["commandKey"],
        "model": value["request"]["model"],
        "state": {"queued": "pending", "done": "applied", "failed": "rejected"}[job["state"]],
    }
    if value["request"].get("allowMetered"):
        result["allowMetered"] = True
    if value.get("reason"):
        result["reason"] = value["reason"]
    return result


class MainModelSelections:
    def __init__(self, executions, wakeup):
        self.executions = executions
        self.db, self.wakeup = executions.db, wakeup

    async def request(self, owner, cid, spec):
        from roami_okr.main_execution import main_binding

        if not spec["commandKey"].strip():
            raise DomainError("INVALID_REQUEST_KEY")
        project = spec["projectId"]
        native_key = (
            "model-selection:"
            + hashlib.sha256(
                encoded([owner, project, cid, spec["commandKey"]]).encode()
            ).hexdigest()
        )

        def write(db):
            assert_project_main(db, owner, cid, project)
            prior = row(db, "SELECT * FROM jobs WHERE dedupe_key=?", (native_key,))
            if prior:
                if json.loads(prior["payload_json"])["request"] != spec:
                    raise DomainError("REQUEST_KEY_CONFLICT", 409)
                return main_model_selection_status(prior)
            if pending_model_selection(db, cid):
                raise DomainError("PROJECT_MAIN_MODEL_SELECTION_PENDING", 409)
            binding = main_binding(db, owner, cid)
            if not binding or binding["executor"] != "claude":
                raise DomainError("PROJECT_MAIN_MODEL_SELECTION_UNAVAILABLE", 409)
            if binding["generation"] != spec["expectedGeneration"]:
                raise DomainError("PROJECT_MAIN_GENERATION_CHANGED", 409)
            if binding["model"] != spec["expectedModel"] or spec["model"] == spec["expectedModel"]:
                raise DomainError("PROJECT_MAIN_MODEL_CONFLICT", 409)
            assert_main_idle(db, owned(db, owner, cid), allow_queued=True)
            if row(db, "SELECT id FROM turns WHERE conversation_id=? AND state='running'", (cid,)):
                raise DomainError("MAIN_BUSY", 409)
            job_id = identity()
            value = {"owner": owner, "request": spec, "launchKey": binding["launch_key"]}
            db.execute(
                "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) "
                "VALUES(?,?,?,?,?,'queued',?)",
                (job_id, JOB_KIND, cid, native_key, encoded(value), now_ms()),
            )
            return main_model_selection_status(row(db, "SELECT * FROM jobs WHERE id=?", (job_id,)))

        result = await self.db.call(write, write=True)
        self.wakeup.set()
        return result

    async def advance(self, job):
        operation = await self.db.call(
            lambda db: claim_model_selection(db, job["id"], JOB_KIND), write=True
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
        }
        if spec.get("allowMetered"):
            request["allowMetered"] = True
        try:
            previous = await self.db.call(lambda db: self.binding(db, operation, value))
            selected = await select_bound_model(
                self.executions.executor.command,
                previous,
                request,
                "PROJECT_MAIN_MODEL_SELECTION_UNCONFIRMED",
            )
            await self.db.call(
                lambda db: self.finish(db, operation, value, previous, selected), write=True
            )
            self.wakeup.set()
        except (DomainError, OSError, TimeoutError) as error:
            code = getattr(error, "code", "CODING_EXECUTOR_UNAVAILABLE")
            log.debug("Project Main model selection is unsettled: %s", code)
            await self.db.call(lambda db: self.observation(db, operation, value, code), write=True)
            self.wakeup.set()

    @staticmethod
    def binding(db, operation, value):
        from roami_okr.main_execution import main_binding

        owner, cid, spec = value["owner"], operation["aggregate_id"], value["request"]
        assert_project_main(db, owner, cid, spec["projectId"])
        binding = main_binding(db, owner, cid)
        if (
            not binding
            or binding["executor"] != "claude"
            or binding["generation"] != spec["expectedGeneration"]
            or binding["launch_key"] != value["launchKey"]
            or binding["model"] != spec["expectedModel"]
        ):
            raise DomainError("PROJECT_MAIN_MODEL_SELECTION_UNCONFIRMED", 409)
        return binding

    def finish(self, db, operation, value, previous, selected):
        if not model_selection_still_claimed(db, operation):
            return
        current = self.binding(db, operation, value)
        if current != previous:
            raise DomainError("PROJECT_MAIN_MODEL_SELECTION_UNCONFIRMED", 409)
        db.execute(
            "UPDATE project_okr_main_providers SET model=? WHERE launch_key=?",
            (selected["model"], current["launch_key"]),
        )
        value.pop("reason", None)
        db.execute(
            "UPDATE jobs SET state='done',payload_json=? WHERE id=?",
            (encoded(value), operation["id"]),
        )
        event(
            db,
            current["conversation_id"],
            "project.main.execution.changed",
            {
                "generation": current["generation"],
                "model": selected["model"],
                "previousModel": current["model"],
                "sessionId": current["session_id"],
                "commandKey": value["request"]["commandKey"],
                "proofSha256": selected["proof"]["sourceSha256"],
            },
        )

    def observation(self, db, operation, value, code):
        if not model_selection_still_claimed(db, operation):
            return
        value["reason"] = code
        db.execute(
            "UPDATE jobs SET state=?,payload_json=? WHERE id=?",
            ("failed" if code in BEFORE_INPUT else "queued", encoded(value), operation["id"]),
        )
