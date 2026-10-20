"""Durable user steering waits for stop proof before admitting a new task revision."""

import json

from roami_agent.conversation.activity_events import activity_event as event
from roami_agent.dispatch.task_cancellation import request_task_cancellation
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row, rows
from roami_agent.storage.transcript_repository import message, owned

STABLE = {"succeeded", "failed", "cancelled", "interrupted", "waiting_user"}


class TaskRevisions:
    def __init__(self, database):
        self.db = database

    @staticmethod
    def _receipt(job):
        payload = json.loads(job["payload_json"])
        return {
            "operationId": job["id"],
            "taskId": job["aggregate_id"],
            "state": payload.get("status", "stopping"),
            "revision": payload.get("appliedRevision", payload["expectedRevision"]),
            "errorCode": payload.get("errorCode"),
            "text": payload["text"],
        }

    async def get(self, owner, task_id, operation_id):
        def read(db):
            job = row(
                db,
                "SELECT j.* FROM jobs j JOIN tasks t ON t.id=j.aggregate_id "
                "WHERE j.id=? AND j.aggregate_id=? AND j.kind='task.steer' AND t.owner_id=?",
                (operation_id, task_id, owner),
            )
            if not job:
                raise DomainError("TASK_STEER_NOT_FOUND", 404)
            return self._receipt(job)

        return await self.db.call(read)

    async def request(
        self,
        owner,
        task_id,
        text,
        expected_revision,
        key,
        *,
        source_turn_id=None,
        source_conversation_id=None,
    ):
        if (
            not isinstance(text, str)
            or not text.strip()
            or not isinstance(key, str)
            or not key
            or len(key) > 200
            or isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 1
        ):
            raise DomainError("INVALID_TASK_STEER")
        spec = {"expectedRevision": expected_revision, "text": text}

        def write(db):
            if source_turn_id:
                source = row(
                    db,
                    "SELECT t.* FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=? AND c.owner_id=? AND t.state='running'",
                    (source_turn_id, owner),
                )
                if not source or source["conversation_id"] != source_conversation_id:
                    raise DomainError("TASK_TURN_INACTIVE", 409)
                assert_context_admitted(db, dict(source, owner_id=owner))
                if source["trigger_kind"] == "completion":
                    raise DomainError("TASK_STEER_USER_REQUEST_REQUIRED", 409)
            task = row(db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (task_id, owner))
            if not task:
                raise DomainError("TASK_NOT_FOUND", 404)
            owned(db, owner, task["origin_conversation_id"])
            if source_conversation_id and task["origin_conversation_id"] != source_conversation_id:
                raise DomainError("TASK_SOURCE_CONVERSATION_MISMATCH", 409)
            dedupe = "task.steer:" + owner + ":" + key
            previous = row(db, "SELECT * FROM jobs WHERE dedupe_key=?", (dedupe,))
            if previous:
                payload = json.loads(previous["payload_json"])
                if previous["aggregate_id"] != task_id or any(
                    payload.get(k) != v for k, v in spec.items()
                ):
                    raise DomainError("TASK_STEER_KEY_CONFLICT", 409)
                return self._receipt(previous)
            if task["revision"] != expected_revision:
                raise DomainError("TASK_REVISION_CHANGED", 409)
            if row(
                db,
                "SELECT id FROM jobs WHERE kind='task.steer' AND aggregate_id=? AND state='queued'",
                (task_id,),
            ):
                raise DomainError("TASK_STEER_PENDING", 409)
            if row(
                db,
                "SELECT 1 FROM context_omissions WHERE owner_id=? AND message_id=?",
                (owner, task["origin_message_id"]),
            ):
                raise DomainError("TASK_SOURCE_FORGOTTEN", 409)
            if task["state"] in STABLE:
                run = row(
                    db,
                    "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
                    (task_id, task["revision"]),
                )
                result = json.loads(run["result_json"]) if run and run["result_json"] else {}
                if (
                    result.get("outcomeKnown") is False
                    or result.get("inputStopped") is False
                    or run
                    and run["state"] == "unknown"
                    and (run["executor_kind"] == "cli" or task["target_json"])
                ):
                    raise DomainError("TASK_OUTCOME_UNRESOLVED", 409)
            intent = json.loads(task["intent_json"])
            goal = intent["goal"] + "\n\nAdditional user requirements:\n" + text
            operation = identity()
            mid = message(
                db,
                task["origin_conversation_id"],
                task["origin_branch_id"],
                "user",
                {
                    "text": text,
                    "taskSteer": task_id,
                    "operationId": operation,
                    "taskRevision": expected_revision,
                },
            )
            payload = {
                **spec,
                "goal": goal,
                "messageId": mid,
                "status": "stopping",
                "stateAtRequest": task["state"],
            }
            db.execute(
                "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) "
                "VALUES(?,'task.steer',?,?,?,'queued',?)",
                (operation, task_id, dedupe, encoded(payload), now_ms()),
            )
            event(
                db,
                task["origin_conversation_id"],
                "task.steer_requested",
                {
                    "taskId": task_id,
                    "operationId": operation,
                    "revision": expected_revision,
                    "messageId": mid,
                },
                task_id=task_id,
                message_id=mid,
            )
            if task["state"] not in STABLE:
                request_task_cancellation(db, owner, task_id)
            else:
                for child in rows(
                    db,
                    "SELECT id FROM tasks WHERE parent_task_id=? AND state NOT IN ('succeeded','failed','cancelled','interrupted')",
                    (task_id,),
                ):
                    request_task_cancellation(db, owner, child["id"])
            return self._receipt(row(db, "SELECT * FROM jobs WHERE id=?", (operation,)))

        return await self.db.call(write, write=True)

    @staticmethod
    def _blocked(db, task, run, payload):
        owner = task["owner_id"]
        for mid in (task["origin_message_id"], payload["messageId"]):
            if row(
                db,
                "SELECT 1 FROM context_omissions WHERE owner_id=? AND message_id=?",
                (owner, mid),
            ):
                return "TASK_SOURCE_FORGOTTEN"
        if task["parent_task_id"]:
            parent = row(
                db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (task["parent_task_id"], owner)
            )
            generation = json.loads(task["intent_json"]).get("parentTaskRevision", 1)
            if (
                not parent
                or parent["state"] not in {"running", "verifying"}
                or parent["revision"] != generation
            ):
                return "PARENT_TASK_NOT_RUNNING"
            if (
                deadline := json.loads(parent["budget_json"]).get("deadlineMs")
            ) and deadline <= now_ms():
                return "TASK_BUDGET_EXCEEDED"
        tree = "WITH RECURSIVE tree(id) AS (SELECT ? UNION SELECT t.id FROM tasks t JOIN tree ON t.parent_task_id=tree.id) "
        if row(
            db,
            tree + "SELECT 1 FROM resources WHERE owner_task_id IN (SELECT id FROM tree) "
            "AND (lease_until_ms IS NOT NULL OR state NOT IN ('idle')) LIMIT 1",
            (task["id"],),
        ):
            return "TASK_RESOURCE_NOT_RELEASED"
        if row(
            db,
            tree
            + "SELECT 1 FROM tool_calls x JOIN turns t ON t.id=x.turn_id JOIN task_attempts a ON a.native_branch_id=t.branch_id "
            "WHERE a.task_id IN (SELECT id FROM tree) AND x.effect='write' AND x.state IN ('planned','running','unknown') LIMIT 1",
            (task["id"],),
        ):
            return "TASK_OUTCOME_UNRESOLVED"
        if row(
            db,
            tree
            + "SELECT 1 FROM tasks WHERE id IN (SELECT id FROM tree) AND id!=? AND state NOT IN ('succeeded','failed','cancelled','interrupted') LIMIT 1",
            (task["id"], task["id"]),
        ):
            return "TASK_CHILDREN_NOT_STOPPED"
        if row(
            db,
            tree
            + "SELECT 1 FROM turns t JOIN task_attempts a ON a.native_branch_id=t.branch_id WHERE a.task_id IN (SELECT id FROM tree) AND t.state='running' LIMIT 1",
            (task["id"],),
        ):
            return "TASK_EXECUTION_NOT_STOPPED"
        result = json.loads(run["result_json"]) if run["result_json"] else {}
        if result.get("outcomeKnown") is False or result.get("inputStopped") is False:
            return "TASK_OUTCOME_UNRESOLVED"
        if run["state"] == "unknown" and (run["executor_kind"] == "cli" or task["target_json"]):
            return "TASK_OUTCOME_UNRESOLVED"
        return None

    async def advance(self):
        def write(db):
            for job in rows(
                db,
                "SELECT * FROM jobs WHERE kind='task.steer' AND state='queued' ORDER BY rowid LIMIT 32",
            ):
                payload = json.loads(job["payload_json"])
                task = row(db, "SELECT * FROM tasks WHERE id=?", (job["aggregate_id"],))
                if task["state"] not in STABLE:
                    continue
                if row(
                    db,
                    "WITH RECURSIVE tree(id) AS (SELECT id FROM tasks WHERE parent_task_id=? UNION SELECT t.id FROM tasks t JOIN tree ON t.parent_task_id=tree.id) SELECT 1 FROM tasks WHERE id IN (SELECT id FROM tree) AND state NOT IN ('succeeded','failed','cancelled','interrupted') LIMIT 1",
                    (task["id"],),
                ):
                    continue
                run = row(
                    db,
                    "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
                    (task["id"], task["revision"]),
                )
                error = (
                    "TASK_REVISION_CHANGED"
                    if task["revision"] != payload["expectedRevision"]
                    else self._blocked(db, task, run, payload)
                )
                if error:
                    payload.update(status="blocked", errorCode=error)
                    db.execute(
                        "UPDATE jobs SET state='failed',payload_json=? WHERE id=?",
                        (encoded(payload), job["id"]),
                    )
                    event(
                        db,
                        task["origin_conversation_id"],
                        "task.steer_blocked",
                        {"taskId": task["id"], "operationId": job["id"], "errorCode": error},
                        task_id=task["id"],
                    )
                    continue
                intent = json.loads(task["intent_json"])
                intent.setdefault("initialIntent", dict(intent))
                previous = intent.get("continuation", {})
                verified_through = (
                    task["revision"]
                    if task["state"] == "succeeded"
                    else previous.get("verifiedThroughRevision", 0)
                )
                unfinished_children = row(
                    db,
                    "SELECT id FROM tasks WHERE parent_task_id=? AND COALESCE(json_extract(intent_json,'$.parentTaskRevision'),1)=? AND state!='succeeded' LIMIT 1",
                    (task["id"], task["revision"]),
                )
                requires_acceptance = task["state"] != "succeeded" and (
                    task["state"] == "waiting_user"
                    or payload.get("stateAtRequest") == "waiting_user"
                    or previous.get("requiresAcceptance", False)
                    or bool(unfinished_children)
                )
                intent["continuation"] = {
                    "verifiedThroughRevision": verified_through,
                    "requiresAcceptance": requires_acceptance,
                    "runId": run["id"],
                    "state": run["state"],
                    "summary": (
                        json.loads(run["result_json"]).get("summary", "")[:6000]
                        if run["result_json"]
                        else ""
                    ),
                }
                intent.update(
                    goal=payload["goal"],
                    sourceMessageIds=list(
                        dict.fromkeys(
                            [*intent.get("sourceMessageIds", []), task["origin_message_id"]]
                        )
                    ),
                )
                if intent["target"]["kind"] == "new_project":
                    intent.setdefault("provisionLaunchId", run["launch_id"])
                target = json.loads(task["target_json"]) if task["target_json"] else {}
                if intent["target"]["kind"] != "session" and target.get("workspaceId"):
                    intent["target"] = (
                        {
                            "kind": "project",
                            "projectId": target["projectId"],
                            "workspaceId": target["workspaceId"],
                        }
                        if target.get("projectId")
                        else {"kind": "new_session", "directory": target["workdir"]}
                    )
                revision, rid = task["revision"] + 1, identity()
                budget = json.loads(task["budget_json"])
                budget.update(usedSteps=0, maxTurns=0, timeoutMs=0, deadlineMs=0)
                if run["native_branch_id"]:
                    branch = row(
                        db,
                        "SELECT conversation_id FROM branches WHERE id=?",
                        (run["native_branch_id"],),
                    )
                    message(
                        db,
                        branch["conversation_id"],
                        run["native_branch_id"],
                        "user",
                        {
                            "text": "Continue the existing task; preserve completed work and inspect current state before changes. Updated goal:\n"
                            + payload["goal"],
                            "taskRevision": revision,
                        },
                    )
                db.execute(
                    "UPDATE tasks SET revision=?,state='queued',intent_json=?,origin_message_id=?,budget_json=?,updated_ms=? WHERE id=?",
                    (
                        revision,
                        encoded(intent),
                        payload["messageId"],
                        encoded(budget),
                        now_ms(),
                        task["id"],
                    ),
                )
                attempt_no = db.execute(
                    "SELECT MAX(attempt_no)+1 FROM task_attempts WHERE task_id=?", (task["id"],)
                ).fetchone()[0]
                db.execute(
                    "INSERT INTO task_attempts(id,task_id,task_revision,attempt_no,executor_kind,launch_id,state,native_branch_id,lease_epoch) VALUES(?,?,?,?,?,?,'accepted',?,?)",
                    (
                        rid,
                        task["id"],
                        revision,
                        attempt_no,
                        run["executor_kind"],
                        "task-revision:" + job["id"],
                        run["native_branch_id"],
                        run["lease_epoch"] + 1,
                    ),
                )
                db.execute(
                    "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) VALUES(?,'task.run',?,?,?,'queued',?)",
                    (identity(), task["id"], "run:" + rid, encoded({"runId": rid}), now_ms()),
                )
                payload.update(status="applied", appliedRevision=revision, runId=rid)
                db.execute(
                    "UPDATE jobs SET state='done',payload_json=? WHERE id=?",
                    (encoded(payload), job["id"]),
                )
                event(
                    db,
                    task["origin_conversation_id"],
                    "task.steered",
                    {
                        "taskId": task["id"],
                        "operationId": job["id"],
                        "revision": revision,
                        "runId": rid,
                    },
                    task_id=task["id"],
                )

        await self.db.call(write, write=True)
