"Durable delegation, native child branches and revision-bound executor reports."

import json
from pathlib import Path

from roami_agent.conversation.activity import conversation_activity
from roami_agent.conversation.activity_events import activity_event as event
from roami_agent.conversation.activity_payloads import activity_payload
from roami_agent.dispatch.navigation_recovery import stopped_navigation
from roami_agent.dispatch.task_cancellation import request_task_cancellation
from roami_agent.dispatch.task_revisions import TaskRevisions
from roami_agent.dispatch.task_sessions import session_closure
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row, rows
from roami_agent.storage.native_session_registry import register as register_native_session
from roami_agent.storage.task_context import model_task_projection
from roami_agent.storage.task_continuation import continuation_candidates
from roami_agent.storage.transcript_repository import history, message, owned

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


class Tasks:
    def __init__(
        self,
        database,
        conversations,
        *,
        max_depth=0,
        max_children=0,
    ):
        self.db, self.conversations = database, conversations
        self.max_depth, self.max_children = max_depth, max_children
        self.revisions = TaskRevisions(database)
        self.deliverables = None

    @staticmethod
    def cancel_forgotten_in_transaction(db, owner):
        affected = rows(
            db,
            "SELECT t.id FROM tasks t JOIN context_omissions o "
            "ON o.owner_id=t.owner_id AND o.message_id=t.origin_message_id "
            "WHERE t.owner_id=? AND t.state NOT IN "
            "('succeeded','failed','cancelled','interrupted','cancelling')",
            (owner,),
        )
        for task in affected:
            current = row(db, "SELECT state FROM tasks WHERE id=?", (task["id"],))
            if current["state"] != "cancelling":
                request_task_cancellation(db, owner, task["id"])

    async def create(
        self,
        owner,
        cid,
        goal,
        *,
        key,
        parent_task_id=None,
        executor="native",
        model=None,
        target=None,
        from_message_id=None,
        origin_message_id=None,
        record_intent=False,
        source_turn_id=None,
        source_assistant_message_id=None,
        routing_decision=None,
        title=None,
        independent_project_outcome=False,
    ):
        if (
            not key
            or len(key) > 200
            or not goal.strip()
            or executor not in {"native", "codex", "claude", "opencode", "pi"}
        ):
            raise DomainError("INVALID_TASK")
        if model is not None and (
            executor == "native"
            or target
            and target.get("kind") == "session"
            or not isinstance(model, str)
            or not model.strip()
            or len(model) > 300
        ):
            raise DomainError("INVALID_TASK_MODEL")
        if title is not None:
            if not isinstance(title, str) or not title.strip() or len(title) > 80:
                raise DomainError("INVALID_TASK")
            title = " ".join(title.split())
        target = target or {"kind": "new_session"}
        if (
            target.get("kind") == "new_session"
            and target.get("resourceOnly") is True
            and target.get("directory") == ""
        ):
            target = {key: value for key, value in target.items() if key != "directory"}
        if target.get("kind") not in {"project", "session", "new_session", "new_project"}:
            raise DomainError("INVALID_TASK_TARGET")
        if target.get("kind") == "new_session" and "baseDir" in target:
            raise DomainError("LOOSE_SESSION_USE_DIRECTORY")
        if "resourceOnly" in target and (
            type(target["resourceOnly"]) is not bool
            or target["resourceOnly"]
            and (
                executor != "native"
                or from_message_id is not None
                or target["kind"] != "new_session"
                or target.get("nodeId", "local") != "local"
                or any(
                    target.get(name)
                    for name in [
                        "directory",
                        "workspaceId",
                        "projectId",
                        "sessionId",
                        "base",
                        "remote",
                        "name",
                        "baseDir",
                    ]
                )
            )
        ):
            raise DomainError("INVALID_RESOURCE_ONLY_TARGET")
        if executor in {"codex", "claude", "opencode", "pi"} and target.get("kind") == "session":
            if not isinstance(target.get("sessionId"), str) or not target["sessionId"]:
                raise DomainError("CODING_SESSION_ID_REQUIRED")
            if any(target.get(k) for k in ["directory", "workspaceId", "base", "remote"]):
                raise DomainError("CODING_SESSION_TARGET_CONFLICT")
        spec = {
            "goal": goal,
            "target": target,
            "executor": executor,
            "fromMessageId": from_message_id,
            "parentTaskId": parent_task_id,
            "originMessageId": origin_message_id,
            "recordIntent": record_intent,
        }

        if model is not None:
            spec["model"] = model
        if title is not None:
            spec["title"] = title
        if routing_decision is not None:
            spec["routingDecision"] = routing_decision
        if source_turn_id or source_assistant_message_id:
            spec.update(
                sourceTurnId=source_turn_id,
                sourceAssistantMessageId=source_assistant_message_id,
            )

        def write(db):
            c = owned(db, owner, cid)
            if source_turn_id or source_assistant_message_id:
                if not row(
                    db,
                    "SELECT m.id FROM messages m JOIN turns t ON t.id=m.turn_id "
                    "WHERE m.id=? AND t.id=? AND t.conversation_id=? AND m.role='assistant'",
                    (source_assistant_message_id, source_turn_id, cid),
                ):
                    raise DomainError("INVALID_TASK_SOURCE", 409)
                assert_context_admitted(db, {"id": source_turn_id, "owner_id": owner})
                if not row(
                    db,
                    "SELECT id FROM turns WHERE id=? AND state='running'",
                    (source_turn_id,),
                ):
                    raise DomainError("TASK_TURN_INACTIVE", 409)
            launch_id = "task:" + owner + ":" + key
            attempt = row(db, "SELECT * FROM task_attempts WHERE launch_id=?", (launch_id,))
            if attempt:
                task = row(db, "SELECT * FROM tasks WHERE id=?", (attempt["task_id"],))
                stored_spec = json.loads(task["intent_json"])
                stored_spec = dict(stored_spec.get("initialIntent", stored_spec))
                stored_spec.pop("parentTaskRevision", None)
                if stored_spec != spec or task["origin_conversation_id"] != cid:
                    raise DomainError("TASK_KEY_CONFLICT", 409)
                return task
            if (
                source_turn_id
                and not parent_task_id
                and not from_message_id
                and continuation_candidates(db, owner, cid, source_turn_id, target)
            ):
                raise DomainError("TASK_CONTINUATION_REQUIRED", 409)
            if source_turn_id:
                for rejection in rows(
                    db,
                    "SELECT x.arguments_json,m.content_json FROM tool_calls x "
                    "JOIN messages m ON m.id=x.result_message_id WHERE x.turn_id=? "
                    "AND x.tool_name IN ('delegate','session_send') AND x.state='failed'",
                    (source_turn_id,),
                ):
                    rejected_result = json.loads(json.loads(rejection["content_json"])["text"])
                    error = rejected_result.get("error")
                    if error == "TASK_SESSION_BINDING_REQUIRED":
                        raise DomainError("TASK_OUTCOME_UNRESOLVED", 409)
                    if error in {
                        "ROUTING_EXECUTOR_CONFLICT",
                        "ROUTING_EXPLICIT_UNAVAILABLE",
                    }:
                        rejected_args = json.loads(rejection["arguments_json"])
                        requested = (rejected_args.get("routing") or {}).get(
                            "explicitExecutor"
                        ) or rejected_args.get("executor")
                        if requested and executor != requested:
                            raise DomainError("ROUTING_EXECUTOR_CONFLICT", 409)
                rejected = row(
                    db,
                    "SELECT x.id FROM tool_calls x JOIN messages m ON m.id=x.result_message_id "
                    "WHERE x.turn_id=? AND x.tool_name='delegate' AND x.state='failed' AND "
                    "CASE WHEN json_valid(json_extract(native_content(m.content_json),'$.text')) THEN "
                    "json_extract(json_extract(native_content(m.content_json),'$.text'),'$.error') END "
                    "IN ('INVALID_EXECUTION_DIRECTORY','EXECUTION_DIRECTORY_UNAVAILABLE') LIMIT 1",
                    (source_turn_id,),
                )
                if rejected:
                    raise DomainError("TASK_TARGET_REVIEW_REQUIRED", 409)
                for steering in rows(
                    db,
                    "SELECT arguments_json FROM tool_calls WHERE turn_id=? "
                    "AND tool_name='task_steer' AND state='succeeded'",
                    (source_turn_id,),
                ):
                    previous_id = json.loads(steering["arguments_json"])["taskId"]
                    previous = row(
                        db,
                        "SELECT intent_json FROM tasks WHERE id=? AND owner_id=?",
                        (previous_id, owner),
                    )
                    old_target = json.loads(previous["intent_json"])["target"] if previous else {}
                    same_project = (
                        target.get("kind") == "project"
                        and target.get("projectId")
                        and target.get("projectId") == old_target.get("projectId")
                        and not target.get("workspaceId")
                    )
                    if (
                        previous_id in goal
                        or (same_project and not independent_project_outcome)
                        or any(
                            target.get(key) and target.get(key) == old_target.get(key)
                            for key in ("workspaceId", "sessionId", "directory")
                        )
                    ):
                        raise DomainError("TASK_CONTINUATION_ALREADY_REQUESTED", 409)
            path_key = {"new_session": "directory", "new_project": "baseDir"}.get(target["kind"])
            if path_key and path_key in target:
                directory = target[path_key]
                if (
                    not isinstance(directory, str)
                    or not directory
                    or not Path(directory).is_absolute()
                ):
                    raise DomainError("INVALID_EXECUTION_DIRECTORY")
                try:
                    available = Path(directory).is_dir()
                except (OSError, ValueError):
                    available = False
                if not available:
                    raise DomainError("EXECUTION_DIRECTORY_UNAVAILABLE")
            parent, depth = None, 0
            if parent_task_id:
                parent = row(
                    db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (parent_task_id, owner)
                )
                if not parent or parent["state"] != "running":
                    raise DomainError("PARENT_TASK_NOT_RUNNING", 409)
                depth = json.loads(parent["budget_json"])["depth"] + 1
                spec["parentTaskRevision"] = parent["revision"]
            if self.max_depth and depth > self.max_depth:
                raise DomainError("TASK_DEPTH_EXCEEDED", 409)
            if parent:
                active = db.execute(
                    "SELECT COUNT(*) FROM tasks WHERE parent_task_id=? AND state NOT IN "
                    "('succeeded','failed','cancelled','interrupted')",
                    (parent["id"],),
                ).fetchone()[0]
                if self.max_children and active >= self.max_children:
                    raise DomainError("TASK_CONCURRENCY_EXCEEDED", 409)
            transcript = history(db, c["active_branch_id"])
            origin = next(
                (
                    m
                    for m in reversed(transcript)
                    if m["role"] == "user"
                    and (not origin_message_id or m["id"] == origin_message_id)
                ),
                None,
            )
            if record_intent:
                mid = message(
                    db, cid, c["active_branch_id"], "user", {"text": goal, "taskIntent": True}
                )
                origin = row(db, "SELECT * FROM messages WHERE id=?", (mid,))
                event(db, cid, "task.intent", {"messageId": mid}, message_id=mid)
            if not origin:
                raise DomainError("TASK_REQUIRES_ORIGIN_MESSAGE", 409)
            if source_turn_id and not parent_task_id:
                previous = rows(
                    db,
                    "SELECT * FROM tasks WHERE owner_id=? AND origin_conversation_id=? "
                    "AND origin_message_id=? AND parent_task_id IS NULL ORDER BY created_ms DESC",
                    (owner, cid, origin["id"]),
                )
                for existing in previous:
                    intent = json.loads(existing["intent_json"])
                    if (
                        intent.get("goal", "").strip() == goal.strip()
                        and intent.get("target") == target
                    ):
                        # A new tool-call ID must not duplicate an already admitted assignment.
                        return existing
                unknown = any(
                    row(
                        db,
                        "SELECT id FROM task_attempts WHERE task_id=? AND "
                        "(state='unknown' OR json_extract(result_json,'$.outcomeKnown')=0) LIMIT 1",
                        (t["id"],),
                    )
                    for t in previous
                )
                unresolved_setup = any(
                    json.loads(t["intent_json"]).get("target") == target
                    and t["state"] == "failed"
                    and row(
                        db,
                        "SELECT id FROM task_attempts WHERE task_id=? AND "
                        "json_extract(result_json,'$.summary') IN "
                        "('MODEL_HTTP_401','MODEL_HTTP_403','NATIVE_WORKSPACE_UNAVAILABLE',"
                        "'PROJECT_PROVISION_UNAVAILABLE','WORKSPACE_STALE','UNKNOWN_WORKSPACE',"
                        "'WORKSPACE_PROJECT_MISMATCH','WORKSPACE_PREPARATION_FAILED',"
                        "'UNKNOWN_PROJECT','PROJECT_CATALOG_UNAVAILABLE','PROJECT_HAS_NO_GIT',"
                        "'INVALID_PROJECT_DIRECTORY','INVALID_WORKSPACE_TARGET','WORKSPACE_BUSY',"
                        "'INVALID_EXECUTION_DIRECTORY','EXECUTION_DIRECTORY_UNAVAILABLE') "
                        "ORDER BY task_revision DESC,attempt_no DESC LIMIT 1",
                        (t["id"],),
                    )
                    for t in previous
                )
                if unknown or unresolved_setup:
                    raise DomainError("TASK_FAILURE_REVIEW_REQUIRED", 409)
            fork_point = None
            if from_message_id:
                fork_point = next((m for m in transcript if m["id"] == from_message_id), None)
                if (
                    not fork_point
                    or fork_point["role"] != "assistant"
                    or fork_point["status"] != "completed"
                    or json.loads(fork_point["content_json"]).get("tool_calls")
                    or (
                        fork_point["turn_id"]
                        and not row(
                            db,
                            "SELECT id FROM turns WHERE id=? AND state='completed'",
                            (fork_point["turn_id"],),
                        )
                    )
                ):
                    raise DomainError("FORK_REQUIRES_COMPLETED_ROUND", 409)
            tid, rid = identity(), identity()
            db.execute(
                "INSERT INTO tasks(id,owner_id,origin_conversation_id,origin_branch_id,origin_message_id,"
                "parent_task_id,intent_json,state,budget_json,created_ms,updated_ms) VALUES(?,?,?,?,?,?,?,'queued',?,?,?)",
                (
                    tid,
                    owner,
                    cid,
                    c["active_branch_id"],
                    origin["id"],
                    parent_task_id,
                    encoded(spec),
                    encoded(
                        {
                            "depth": depth,
                            "maxTurns": 0,
                            "timeoutMs": 0,
                            "deadlineMs": json.loads(parent["budget_json"]).get("deadlineMs", 0)
                            if parent
                            else 0,
                        }
                    ),
                    now_ms(),
                    now_ms(),
                ),
            )
            branch_id = None
            if executor == "native":
                child, branch_id = identity(), identity()
                db.execute(
                    "INSERT INTO conversations(id,owner_id,title,created_ms,updated_ms) VALUES(?,?,?,?,?)",
                    (child, owner, "Task: " + goal[:100], now_ms(), now_ms()),
                )
                db.execute(
                    "INSERT INTO branches(id,conversation_id,parent_branch_id,fork_message_id,created_ms) VALUES(?,?,?,?,?)",
                    (
                        branch_id,
                        child,
                        fork_point["branch_id"] if fork_point else None,
                        from_message_id,
                        now_ms(),
                    ),
                )
                db.execute(
                    "UPDATE conversations SET active_branch_id=? WHERE id=?", (branch_id, child)
                )
                register_native_session(db, tid, child, branch_id)
                seed = goal
                if (spec.get("target") or {}).get("resourceOnly"):
                    original = json.loads(origin["content_json"]).get("text", "")
                    seed = (
                        "Original user request (defines the requested facts and scope):\n"
                        + original
                        + "\n\nDelegated goal (context only; do not broaden or change the original request):\n"
                        + goal
                    )
                source_content = json.loads(origin["content_json"])
                child_content = {"text": seed}
                if source_content.get("attachments"):
                    child_content["attachments"] = source_content["attachments"]
                message(db, child, branch_id, "user", child_content)
            db.execute(
                "INSERT INTO task_attempts(id,task_id,task_revision,attempt_no,executor_kind,launch_id,"
                "state,native_branch_id,lease_epoch) VALUES(?,?,1,1,?,?,'accepted',?,1)",
                (rid, tid, "native" if executor == "native" else "cli", launch_id, branch_id),
            )
            db.execute(
                "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) "
                "VALUES(?,'task.run',?,?,?,'queued',?)",
                (identity(), tid, "run:" + rid, encoded({"runId": rid}), now_ms()),
            )
            event(
                db,
                cid,
                "task.accepted",
                {"taskId": tid, "runId": rid},
                key="accepted:" + tid,
                task_id=tid,
            )
            return row(db, "SELECT * FROM tasks WHERE id=?", (tid,))

        return await self.db.call(write, write=True)

    @staticmethod
    def _view(db, task):
        native = row(
            db, "SELECT id,conversation_id FROM native_sessions WHERE task_id=?", (task["id"],)
        )
        task["nativeSession"] = (
            {"id": native["id"], "conversationId": native["conversation_id"]} if native else None
        )
        task["sessionClosure"] = session_closure(db, task["id"])
        target = json.loads(task.get("target_json") or "null") or json.loads(
            task["intent_json"]
        ).get("target", {})
        task["projectId"] = target.get("projectId")
        task["latestAttempt"] = row(
            db,
            "SELECT id AS runId,state,session_id AS sessionId,agent_conversation_id AS agentConversationId,executor_kind AS executorKind,result_json AS inspectionResultJson,"
            "CASE WHEN task_revision=? AND json_valid(result_json) THEN CASE "
            "WHEN json_type(result_json,'$.summary')='text' THEN substr(json_extract(result_json,'$.summary'),1,240) END END AS summary "
            "FROM task_attempts WHERE task_id=? ORDER BY attempt_no DESC LIMIT 1",
            (task["revision"], task["id"]),
        )
        if task["latestAttempt"]:
            result_json = task["latestAttempt"].pop("inspectionResultJson")
            result = json.loads(result_json) if result_json else {}
            task["latestAttempt"]["outcomeKnown"] = result.get(
                "outcomeKnown", False if task["latestAttempt"]["state"] == "unknown" else None
            )
            task["latestAttempt"]["stopConfirmed"] = (
                task["latestAttempt"]["state"] in {"succeeded", "failed", "cancelled"}
                and bool(result)
                and result.get("outcomeKnown") is not False
                and result.get("inputStopped") is not False
            )
            if task["latestAttempt"]["state"] == "unknown":
                run = row(
                    db,
                    "SELECT * FROM task_attempts WHERE id=?",
                    (task["latestAttempt"]["runId"],),
                )
                task["latestAttempt"]["navigationRecoveryAvailable"] = bool(
                    stopped_navigation(db, task, run)
                )
                if task["latestAttempt"]["navigationRecoveryAvailable"]:
                    task["latestAttempt"]["recovery"] = (
                        "This outcome is unknown; previous assistant success claims are not verification. "
                        "For a new user lookup request, continue this original task with task_steer "
                        "at its current revision and retrieve sources again. Status, old reports and "
                        "remembered quotas are not fresh lookup evidence."
                    )
            preparation = row(
                db,
                "SELECT payload_json FROM events WHERE event_key=?",
                ("workspace:" + task["latestAttempt"]["runId"],),
            )
            if preparation:
                task["latestAttempt"]["workspace"] = json.loads(preparation["payload_json"])[
                    "workspace"
                ]
        return task

    async def conversation(self, owner, task_id, run_id=None):
        def read(db):
            task = row(db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (task_id, owner))
            if not task:
                raise DomainError("TASK_NOT_FOUND", 404)
            owned(db, owner, task["origin_conversation_id"])
            if task["origin_message_id"] not in {
                m["id"] for m in history(db, task["origin_branch_id"])
            }:
                raise DomainError("TASK_SOURCE_FORGOTTEN", 404)
            run = row(
                db,
                "SELECT a.*,b.conversation_id FROM task_attempts a "
                "JOIN branches b ON b.id=a.native_branch_id WHERE a.task_id=? "
                + ("AND a.id=? " if run_id else "")
                + "ORDER BY a.attempt_no DESC LIMIT 1",
                (task_id, run_id) if run_id else (task_id,),
            )
            if not run:
                raise DomainError("TASK_CONVERSATION_NOT_FOUND", 404)
            conversation = owned(db, owner, run["conversation_id"])
            started = row(
                db,
                "SELECT turn_id FROM events WHERE task_id=? AND kind IN ('task.started','task.preparing') "
                "AND json_extract(payload_json,'$.runId')=? ORDER BY id LIMIT 1",
                (task_id, run["id"]),
            )
            turn_id = started["turn_id"] if started else None
            return {
                "conversation": conversation,
                "branchId": run["native_branch_id"],
                "messages": [
                    dict(m, content=json.loads(m["content_json"]))
                    for m in history(db, run["native_branch_id"])
                    if m["role"] in {"user", "assistant"} and turn_id and m["turn_id"] == turn_id
                ],
                "turns": [],
                "activities": [],
                "snapshotCursor": 0,
            }

        return await self.db.call(read)

    async def activities(self, owner, task_id, activity_id=None):
        def read(db):
            task = row(db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (task_id, owner))
            if not task:
                raise DomainError("TASK_NOT_FOUND", 404)
            cid, branch = task["origin_conversation_id"], task["origin_branch_id"]
            owned(db, owner, cid)
            if activity_id:
                return activity_payload(db, owner, cid, activity_id, branch, task_id=task_id)
            return conversation_activity(db, cid, history(db, branch), task_id=task_id)

        return await self.db.call(read)

    async def get(self, owner, task_id):
        def read(db):
            task = row(db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (task_id, owner))
            if not task:
                raise DomainError("TASK_NOT_FOUND", 404)
            attempts = rows(
                db,
                "SELECT id,attempt_no AS attemptNo,task_revision AS revision,state,session_id AS sessionId,agent_conversation_id AS agentConversationId,started_ms AS startedMs,finished_ms AS finishedMs,native_branch_id,result_json FROM task_attempts WHERE task_id=? ORDER BY attempt_no DESC LIMIT 21",
                (task_id,),
            )
            for attempt in attempts:
                attempt["hasConversation"] = bool(attempt.pop("native_branch_id"))
                result_json = attempt.pop("result_json")
                attempt["result"] = json.loads(result_json) if result_json else None
            children = rows(
                db,
                "SELECT * FROM tasks WHERE parent_task_id=? AND owner_id=? ORDER BY created_ms DESC LIMIT 101",
                (task_id, owner),
            )
            verdict = row(
                db,
                "SELECT payload_json FROM events WHERE task_id=? "
                "AND kind IN ('task.succeeded','task.failed','task.waiting_user','task.cancelled','task.interrupted') "
                "ORDER BY id DESC LIMIT 1",
                (task_id,),
            )
            payload = json.loads(verdict["payload_json"]) if verdict else {}
            outcome = None
            if (
                payload.get("taskRevision") == task["revision"]
                and attempts
                and payload.get("runId") == attempts[0]["id"]
            ):
                result = payload.get("result", {})
                outcome = {"state": task["state"], "errorCode": result.get("errorCode")}
            return {
                "outcome": outcome,
                "task": self._view(db, task),
                "steering": self.revisions._receipt(steering)
                if (
                    steering := row(
                        db,
                        "SELECT * FROM jobs WHERE aggregate_id=? AND kind='task.steer' ORDER BY rowid DESC LIMIT 1",
                        (task_id,),
                    )
                )
                else None,
                "sessionClosure": session_closure(db, task_id),
                "attempts": attempts[:20],
                "attemptsTruncated": len(attempts) > 20,
                "children": [self._view(db, child) for child in children[:100]],
                "childrenTruncated": len(children) > 100,
            }

        detail = await self.db.call(read)
        if self.deliverables:
            detail["delivery"] = await self.deliverables.collect(owner, detail)
        return detail

    async def list(self, owner, cid=None, *, for_model=False, task_id=None, exclude_task_ids=()):
        def read(db):
            if cid:
                owned(db, owner, cid)
            tasks = rows(
                db,
                "SELECT * FROM tasks WHERE owner_id=?"
                + (" AND origin_conversation_id=?" if cid else "")
                + (" AND id=?" if task_id else "")
                + (" AND id NOT IN (SELECT value FROM json_each(?))" if exclude_task_ids else "")
                + " ORDER BY created_ms DESC LIMIT 200",
                (
                    owner,
                    *((cid,) if cid else ()),
                    *((task_id,) if task_id else ()),
                    *((encoded(list(exclude_task_ids)),) if exclude_task_ids else ()),
                ),
            )
            tasks = [self._view(db, task) for task in tasks]
            return model_task_projection(db, owner, tasks) if for_model else tasks

        return await self.db.call(read)

    async def report(self, owner, task_id, run_id, revision, result):
        if result.get("state") not in {"succeeded", "failed", "cancelled"}:
            raise DomainError("INVALID_TASK_RESULT")

        def write(db):
            task = row(db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (task_id, owner))
            run = row(
                db,
                "SELECT * FROM task_attempts WHERE id=? AND task_id=? AND task_revision=?",
                (run_id, task_id, revision),
            )
            if not task or not run:
                raise DomainError("TASK_RUN_NOT_FOUND", 404)
            if run["result_json"]:
                previous = json.loads(run["result_json"])
                if previous == result:
                    return task
                if (
                    run["state"] != "unknown"
                    or previous.get("outcomeKnown") is not False
                    or result.get("outcomeKnown") is False
                ):
                    raise DomainError("TASK_RESULT_CONFLICT", 409)
                event(
                    db,
                    task["origin_conversation_id"],
                    "task.execution_reconciled",
                    {"taskId": task_id, "runId": run_id, "result": result},
                    task_id=task_id,
                    key="execution-reconciled:" + run_id,
                )
            db.execute(
                "UPDATE task_attempts SET state=?,result_json=?,finished_ms=? WHERE id=?",
                (result["state"], encoded(result), now_ms(), run_id),
            )
            # A late old revision is evidence, never authority over the current task.
            if task["revision"] == revision and task["state"] not in TERMINAL:
                state = "cancelling" if task["state"] == "cancelling" else "verifying"
                db.execute(
                    "UPDATE tasks SET state=?,updated_ms=? WHERE id=?", (state, now_ms(), task_id)
                )
                event(
                    db,
                    task["origin_conversation_id"],
                    "task.result",
                    {"taskId": task_id, "runId": run_id, "state": state},
                    key="result:" + run_id,
                    task_id=task_id,
                )
                db.execute(
                    "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) "
                    "VALUES(?,'task.verify',?,?,?,'queued',?)",
                    (identity(), task_id, "verify:" + run_id, encoded({"runId": run_id}), now_ms()),
                )
            return row(db, "SELECT * FROM tasks WHERE id=?", (task_id,))

        result_task = await self.db.call(write, write=True)
        if self.deliverables:
            await self.get(owner, task_id)
        return result_task

    async def cancel(self, owner, task_id):
        def write(db):
            result = request_task_cancellation(db, owner, task_id)
            pending = rows(
                db,
                "WITH RECURSIVE tree(id) AS (SELECT ? UNION SELECT t.id FROM tasks t JOIN tree ON t.parent_task_id=tree.id) SELECT * FROM jobs WHERE kind='task.steer' AND aggregate_id IN (SELECT id FROM tree) AND state='queued'",
                (task_id,),
            )
            for job in pending:
                payload = json.loads(job["payload_json"])
                payload["status"] = "cancelled"
                db.execute(
                    "UPDATE jobs SET state='done',payload_json=? WHERE id=?",
                    (encoded(payload), job["id"]),
                )
                task = row(
                    db,
                    "SELECT origin_conversation_id FROM tasks WHERE id=?",
                    (job["aggregate_id"],),
                )
                event(
                    db,
                    task["origin_conversation_id"],
                    "task.steer_cancelled",
                    {"taskId": job["aggregate_id"], "operationId": job["id"]},
                    task_id=job["aggregate_id"],
                )
            return result

        return await self.db.call(write, write=True)
