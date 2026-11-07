"""Durable user steering waits for stop proof before admitting a new task revision."""

import asyncio
import json

from roami_agent.conversation.activity_events import activity_event as event
from roami_agent.conversation.attachments import context_attachments
from roami_agent.dispatch.navigation_recovery import recovered_navigation, stopped_navigation
from roami_agent.dispatch.task_cancellation import request_task_cancellation
from roami_agent.dispatch.task_sessions import assert_session_open
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row, rows
from roami_agent.storage.swarm_coordination_tasks import (
    create_authority,
    current_authority,
    request_context,
)
from roami_agent.storage.swarm_repository import group
from roami_agent.storage.swarm_scopes import require_scope
from roami_agent.storage.task_request import member_authorization_context, task_user_request
from roami_agent.storage.transcript_repository import message, owned

STABLE = {"succeeded", "failed", "cancelled", "interrupted", "waiting_user"}


class TaskRevisions:
    def __init__(self, database):
        self.db = database
        self.project_workspace = None

    @staticmethod
    def _receipt(job):
        payload = json.loads(job["payload_json"])
        return {
            "operationId": job["id"],
            "taskId": job["aggregate_id"],
            "state": payload.get("status", "stopping"),
            "revision": payload.get("appliedRevision", payload["expectedRevision"]),
            "errorCode": payload.get("errorCode"),
            "text": payload.get("executionText", payload["text"]),
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
        source_quote=None,
        authorization_quote=None,
        source_lease_epoch=None,
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
        if source_quote is not None:
            if not isinstance(source_quote, str) or not source_quote.strip():
                raise DomainError("INVALID_TASK_STEER")
            spec["sourceQuote"] = source_quote
        if authorization_quote is not None:
            if not isinstance(authorization_quote, str) or not authorization_quote.strip():
                raise DomainError("INVALID_TASK_STEER")
            spec["authorizationQuote"] = authorization_quote

        coordinated = await self.db.call(
            lambda db: request_context(db, owner, source_turn_id, source_lease_epoch)
        )
        project_workspace = None
        if coordinated:
            if self.project_workspace is None:
                raise DomainError("SWARM_COORDINATION_WORKSPACE_REQUIRED", 409)
            project_workspace = await self.project_workspace(coordinated["delegation"]["projectId"])

        def write(db):
            coordinated = request_context(db, owner, source_turn_id, source_lease_epoch)
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
            command_key = (
                "coordination:" + coordinated["id"] + ":" + task_id if coordinated else key
            )
            dedupe = "task.steer:" + owner + ":" + command_key
            previous = row(db, "SELECT * FROM jobs WHERE dedupe_key=?", (dedupe,))
            if previous:
                payload = json.loads(previous["payload_json"])
                if previous["aggregate_id"] != task_id or any(
                    payload.get(k) != v for k, v in spec.items()
                ):
                    raise DomainError("TASK_STEER_KEY_CONFLICT", 409)
                return self._receipt(previous)
            assert_session_open(db, task_id)
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
                    evidence = stopped_navigation(db, task, run)
                    if not evidence:
                        raise DomainError("TASK_OUTCOME_UNRESOLVED", 409)
                    if not recovered_navigation(db, task, run):
                        event(
                            db,
                            task["origin_conversation_id"],
                            "task.navigation_recovery",
                            {
                                "taskId": task_id,
                                "runId": run["id"],
                                "revision": expected_revision,
                                "inputStopped": True,
                                "outcomeKnown": False,
                                "reason": "stopped_navigation_only",
                                **evidence,
                            },
                            task_id=task_id,
                            key="navigation-recovery:" + run["id"],
                        )
            authorization = (
                create_authority(db, task, coordinated, project_workspace) if coordinated else None
            )
            intent = json.loads(task["intent_json"])
            operation = identity()
            source_user = (
                row(
                    db,
                    "SELECT id,content_json FROM messages WHERE turn_id=? AND role='user' AND deleted_ms IS NULL ORDER BY seq LIMIT 1",
                    (source_turn_id,),
                )
                if source_turn_id
                else None
            )
            if coordinated:
                source_user = coordinated["delegation"]["source"]
            team = (
                row(
                    db,
                    "SELECT g.* FROM swarm_groups g JOIN swarm_work_items w ON w.swarm_id=g.id "
                    "WHERE w.task_id=? AND g.owner_id=? AND g.conversation_id=?",
                    (task_id, owner, source_conversation_id),
                )
                if source_turn_id
                else None
            )
            if team:
                require_scope(group(db, owner, team["id"]))
            main_instructions = bool(team and source_user and source_quote is None)
            if source_user:
                # Preserve Main's member assignment separately from its user authorization.
                source_text = (
                    coordinated["delegation"]["source_quote"]
                    if coordinated
                    else json.loads(source_user["content_json"]).get("text", "")
                )
                if any(
                    quote is not None and quote not in source_text
                    for quote in (source_quote, authorization_quote)
                ):
                    raise DomainError("TASK_STEER_SOURCE_REQUIRED")
                text_for_execution = source_quote or (
                    text
                    if main_instructions
                    else authorization_quote or (text if text in source_text else source_text)
                )
            else:
                if source_quote is not None or authorization_quote is not None:
                    raise DomainError("TASK_STEER_SOURCE_REQUIRED")
                text_for_execution = text
            attachments = (
                json.loads(source_user["content_json"]).get("attachments", [])
                if source_user
                else []
            )
            instruction_kind = (
                "Main's assignment for this member"
                if main_instructions
                else "Additional user requirements"
            )
            goal = intent["goal"] + "\n\n" + instruction_kind + ":\n" + text_for_execution
            mid = message(
                db,
                task["origin_conversation_id"],
                task["origin_branch_id"],
                "user",
                {
                    "text": text_for_execution,
                    "taskSteer": task_id,
                    "operationId": operation,
                    "taskRevision": expected_revision,
                    **({"sourceUserMessageId": source_user["id"]} if source_user else {}),
                    **({"instructionAuthor": "main"} if main_instructions else {}),
                    **({"attachments": attachments} if attachments else {}),
                },
            )
            payload = {
                **spec,
                "executionText": text_for_execution,
                "attachments": attachments,
                "goal": goal,
                "messageId": mid,
                "status": "stopping",
                "stateAtRequest": task["state"],
                **({"instructionAuthor": "main"} if main_instructions else {}),
                **(
                    {"coordinationAuthorization": {**authorization, "operationId": operation}}
                    if authorization
                    else {}
                ),
            }
            db.execute(
                "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) "
                "VALUES(?,'task.steer',?,?,?,'queued',?)",
                (operation, task_id, dedupe, encoded(payload), now_ms()),
            )
            if team:
                from roami_agent.storage.swarm_repository import changed

                db.execute(
                    "INSERT INTO swarm_posts(swarm_id,author,text,task_id,created_ms,delivery_json) "
                    "VALUES(?,'main',?,?,?,?)",
                    (
                        team["id"],
                        text_for_execution,
                        task_id,
                        now_ms(),
                        encoded(
                            {"operationId": operation, "taskId": task_id, "acceptedOnly": True}
                        ),
                    ),
                )
                changed(db, team, "swarm.message_forwarded")
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
        if authorization := payload.get("coordinationAuthorization"):
            try:
                current_authority(db, task, authorization)
            except DomainError as exc:
                return exc.code
        for mid in (task["origin_message_id"], payload["messageId"]):
            source = row(
                db,
                "SELECT * FROM messages WHERE id=? AND conversation_id=? AND role='user' "
                "AND deleted_ms IS NULL",
                (mid, task["origin_conversation_id"]),
            )
            source = task_user_request(db, source) if source else None
            if not source:
                return "TASK_SOURCE_FORGOTTEN"
            if row(
                db,
                "SELECT 1 FROM context_omissions WHERE owner_id=? AND message_id=?",
                (owner, mid),
            ):
                return "TASK_SOURCE_FORGOTTEN"
            content = json.loads(source["content_json"])
            _, evidence = context_attachments(db, owner, content)
            if len(evidence) != len(content.get("attachments", [])):
                return "ATTACHMENT_NOT_FOUND"
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
        pending = rows(
            db,
            tree
            + "SELECT DISTINCT x.id FROM tool_calls x JOIN turns t ON t.id=x.turn_id JOIN task_attempts a ON a.native_branch_id=t.branch_id "
            "WHERE a.task_id IN (SELECT id FROM tree) AND x.effect='write' AND x.state IN ('planned','running','unknown')",
            (task["id"],),
        )
        recovered = set()
        if pending:
            for attempt in rows(
                db, "SELECT * FROM task_attempts WHERE task_id=? AND state='unknown'", (task["id"],)
            ):
                if evidence := recovered_navigation(db, task, attempt):
                    recovered.update(evidence["toolCallIds"])
        if any(call["id"] not in recovered for call in pending):
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
        if (
            result.get("outcomeKnown") is False or result.get("inputStopped") is False
        ) and not recovered_navigation(db, task, run):
            return "TASK_OUTCOME_UNRESOLVED"
        if run["state"] == "unknown" and (run["executor_kind"] == "cli" or task["target_json"]):
            return "TASK_OUTCOME_UNRESOLVED"
        return None

    async def advance(self):
        def candidates(db):
            projects = set()
            for job in rows(
                db,
                "SELECT j.* FROM jobs j JOIN tasks t ON t.id=j.aggregate_id WHERE j.kind='task.steer' AND j.state='queued' AND json_type(j.payload_json,'$.coordinationAuthorization')='object' AND t.state IN ('succeeded','failed','cancelled','interrupted','waiting_user') ORDER BY j.rowid LIMIT 32",
            ):
                payload = json.loads(job["payload_json"])
                task = row(db, "SELECT * FROM tasks WHERE id=?", (job["aggregate_id"],))
                run = row(
                    db,
                    "SELECT * FROM task_attempts WHERE task_id=? AND task_revision=? ORDER BY attempt_no DESC LIMIT 1",
                    (task["id"], task["revision"]),
                )
                if task["revision"] == payload["expectedRevision"] and not self._blocked(
                    db, task, run, payload
                ):
                    projects.add(payload["coordinationAuthorization"]["projectId"])
                if len(projects) == 4:
                    break
            return sorted(projects)

        projects = await self.db.call(candidates)
        if self.project_workspace is not None:
            values = await asyncio.gather(
                *(self.project_workspace(project) for project in projects), return_exceptions=True
            )
        else:
            values = [DomainError("SWARM_COORDINATION_WORKSPACE_REQUIRED", 409) for _ in projects]
        workspaces = dict(zip(projects, values, strict=True))

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
                if not error and (authorization := payload.get("coordinationAuthorization")):
                    if authorization["projectId"] not in workspaces:
                        continue
                    actual = workspaces[authorization["projectId"]]
                    if isinstance(actual, BaseException):
                        error = (
                            actual.code
                            if isinstance(actual, DomainError)
                            else "TARGET_DISCOVERY_UNAVAILABLE"
                        )
                    elif (
                        actual.get("projectId") != authorization["projectId"]
                        or actual.get("directory") != authorization["projectDirectory"]
                    ):
                        error = "SWARM_COORDINATION_WORKSPACE_CHANGED"
                if error:
                    if error == "SWARM_COORDINATION_PAUSED":
                        continue
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
                if payload.get("coordinationAuthorization"):
                    intent["coordinationAuthorization"] = payload["coordinationAuthorization"]
                else:
                    intent.pop("coordinationAuthorization", None)
                previous = intent.get("continuation", {})
                from roami_agent.storage.task_provider import provider_binding

                provider = provider_binding(
                    db,
                    task,
                    run["id"] if run["agent_conversation_id"] else previous.get("providerRunId"),
                    run["attempt_no"],
                )
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
                    "text": payload.get("executionText", payload["text"]),
                    **(
                        {"instructionAuthor": "main"}
                        if payload.get("instructionAuthor") == "main"
                        else {}
                    ),
                    "verifiedThroughRevision": verified_through,
                    "requiresAcceptance": requires_acceptance,
                    "runId": run["id"],
                    "state": run["state"],
                    "summary": (
                        json.loads(run["result_json"]).get("summary", "")[:6000]
                        if run["result_json"]
                        else ""
                    ),
                    **({"providerRunId": provider["id"]} if provider else {}),
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
                if provider or run["executor_kind"] == "cli" and run["session_id"]:
                    session = provider or run
                    intent["target"] = {
                        "kind": "session",
                        "sessionId": session["session_id"],
                        "nodeId": session["node_id"] or "local",
                    }
                elif (
                    intent["target"]["kind"] != "session"
                    and target.get("workspaceId")
                    and not (target.get("workspace") or {}).get("taskDirectory")
                ):
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
                    source = task_user_request(
                        db, row(db, "SELECT * FROM messages WHERE id=?", (payload["messageId"],))
                    )
                    attachments = json.loads(source["content_json"]).get("attachments", [])
                    branch = row(
                        db,
                        "SELECT conversation_id FROM branches WHERE id=?",
                        (run["native_branch_id"],),
                    )
                    execution_text = payload.get("executionText", payload["text"])
                    if payload.get("instructionAuthor") == "main":
                        execution_text = (
                            member_authorization_context(
                                json.loads(source["content_json"]).get("text", "")
                            )
                            + "\n\nMain's assignment for this member:\n"
                            + execution_text
                        )
                    if payload.get("coordinationAuthorization"):
                        execution_text += (
                            "\n\nOngoing delegated goal (authorization limit, not extra work):\n"
                            + encoded(payload["coordinationAuthorization"]["goalQuote"])
                        )
                    message(
                        db,
                        branch["conversation_id"],
                        run["native_branch_id"],
                        "user",
                        {
                            "text": execution_text,
                            "taskRevision": revision,
                            "displayText": payload.get("executionText", payload["text"]),
                            **(
                                {"instructionAuthor": "main"}
                                if payload.get("instructionAuthor") == "main"
                                else {}
                            ),
                            **({"attachments": attachments} if attachments else {}),
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
                from roami_agent.storage.swarm_members import record_round

                record_round(
                    db,
                    task["id"],
                    revision,
                    payload["messageId"],
                    payload.get("executionText", payload["text"]),
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
