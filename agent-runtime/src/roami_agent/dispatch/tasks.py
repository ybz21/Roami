"Durable delegation, native child branches and revision-bound executor reports."

import json

from roami_agent.conversation.activity_events import activity_event as event
from roami_agent.dispatch.task_cancellation import request_task_cancellation
from roami_agent.dispatch.task_revisions import TaskRevisions
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row, rows
from roami_agent.storage.task_context import model_task_projection
from roami_agent.storage.transcript_repository import history, message, owned

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


class Tasks:
    def __init__(self, database, conversations, *, max_depth=2, max_children=3):
        self.db, self.conversations = database, conversations
        self.max_depth, self.max_children = max_depth, max_children
        self.revisions = TaskRevisions(database)

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
        target=None,
        from_message_id=None,
        origin_message_id=None,
        record_intent=False,
        source_turn_id=None,
        source_assistant_message_id=None,
    ):
        if (
            not key
            or len(key) > 200
            or not goal.strip()
            or len(goal) > 20_000
            or executor not in {"native", "codex", "claude"}
        ):
            raise DomainError("INVALID_TASK")
        target = target or {"kind": "new_session"}
        if target.get("kind") not in {"project", "session", "new_session", "new_project"}:
            raise DomainError("INVALID_TASK_TARGET")
        if executor in {"codex", "claude"} and target.get("kind") == "session":
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
            parent, depth = None, 0
            if parent_task_id:
                parent = row(
                    db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (parent_task_id, owner)
                )
                if not parent or parent["state"] != "running":
                    raise DomainError("PARENT_TASK_NOT_RUNNING", 409)
                depth = json.loads(parent["budget_json"])["depth"] + 1
                spec["parentTaskRevision"] = parent["revision"]
            if depth > self.max_depth:
                raise DomainError("TASK_DEPTH_EXCEEDED", 409)
            if parent:
                active = db.execute(
                    "SELECT COUNT(*) FROM tasks WHERE parent_task_id=? AND state NOT IN "
                    "('succeeded','failed','cancelled','interrupted')",
                    (parent["id"],),
                ).fetchone()[0]
                if active >= self.max_children:
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
                            "maxTurns": 16,
                            "deadlineMs": min(
                                now_ms() + 600_000, json.loads(parent["budget_json"])["deadlineMs"]
                            )
                            if parent
                            else now_ms() + 600_000,
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
                message(db, child, branch_id, "user", {"text": goal})
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
        task["latestAttempt"] = row(
            db,
            "SELECT id AS runId,state,session_id AS sessionId,agent_conversation_id AS agentConversationId,executor_kind AS executorKind "
            "FROM task_attempts WHERE task_id=? ORDER BY attempt_no DESC LIMIT 1",
            (task["id"],),
        )
        if task["latestAttempt"]:
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

    async def get(self, owner, task_id):
        def read(db):
            task = row(db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (task_id, owner))
            if not task:
                raise DomainError("TASK_NOT_FOUND", 404)
            attempts = rows(
                db,
                "SELECT id,task_revision AS revision,state,session_id AS sessionId,started_ms AS startedMs,finished_ms AS finishedMs,result_json FROM task_attempts WHERE task_id=? ORDER BY attempt_no DESC LIMIT 21",
                (task_id,),
            )
            for attempt in attempts:
                result_json = attempt.pop("result_json")
                attempt["result"] = json.loads(result_json) if result_json else None
            children = rows(
                db,
                "SELECT * FROM tasks WHERE parent_task_id=? AND owner_id=? ORDER BY created_ms DESC LIMIT 101",
                (task_id, owner),
            )
            return {
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
                "attempts": attempts[:20],
                "attemptsTruncated": len(attempts) > 20,
                "children": [self._view(db, child) for child in children[:100]],
                "childrenTruncated": len(children) > 100,
            }

        return await self.db.call(read)

    async def list(self, owner, cid=None, *, for_model=False):
        def read(db):
            if cid:
                owned(db, owner, cid)
            tasks = rows(
                db,
                "SELECT * FROM tasks WHERE owner_id=?"
                + (" AND origin_conversation_id=?" if cid else "")
                + " ORDER BY created_ms DESC LIMIT 200",
                (owner, cid) if cid else (owner,),
            )
            tasks = [self._view(db, task) for task in tasks]
            return model_task_projection(db, owner, tasks) if for_model else tasks

        return await self.db.call(read)

    async def report(self, owner, task_id, run_id, revision, result):
        if (
            result.get("state") not in {"succeeded", "failed", "cancelled"}
            or len(encoded(result)) > 100_000
        ):
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

        return await self.db.call(write, write=True)

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
