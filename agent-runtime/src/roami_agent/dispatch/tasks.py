"Durable delegation, native child branches and revision-bound executor reports."

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import event, row, rows
from roami_agent.storage.transcript_repository import history, message, owned

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


class Tasks:
    def __init__(self, database, conversations, *, max_depth=2, max_children=3):
        self.db, self.conversations = database, conversations
        self.max_depth, self.max_children = max_depth, max_children

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
        spec = {
            "goal": goal,
            "target": target,
            "executor": executor,
            "fromMessageId": from_message_id,
            "parentTaskId": parent_task_id,
            "originMessageId": origin_message_id,
            "recordIntent": record_intent,
        }

        def write(db):
            c = owned(db, owner, cid)
            launch_id = "task:" + owner + ":" + key
            attempt = row(db, "SELECT * FROM task_attempts WHERE launch_id=?", (launch_id,))
            if attempt:
                task = row(db, "SELECT * FROM tasks WHERE id=?", (attempt["task_id"],))
                if json.loads(task["intent_json"]) != spec or task["origin_conversation_id"] != cid:
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

    async def list(self, owner, cid=None):
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
            for task in tasks:
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
                        task["latestAttempt"]["workspace"] = json.loads(
                            preparation["payload_json"]
                        )["workspace"]
            return tasks

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
            root = row(db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (task_id, owner))
            if not root:
                raise DomainError("TASK_NOT_FOUND", 404)
            children = rows(
                db,
                "WITH RECURSIVE tree(id) AS (SELECT ? UNION ALL "
                "SELECT t.id FROM tasks t JOIN tree ON t.parent_task_id=tree.id) "
                "SELECT t.* FROM tasks t JOIN tree ON tree.id=t.id",
                (task_id,),
            )
            for task in children:
                if task["state"] not in TERMINAL:
                    db.execute(
                        "UPDATE tasks SET state='cancelling',updated_ms=? WHERE id=?",
                        (now_ms(), task["id"]),
                    )
                    event(
                        db,
                        task["origin_conversation_id"],
                        "task.cancelling",
                        {"taskId": task["id"]},
                        task_id=task["id"],
                    )
                    run = row(
                        db,
                        "SELECT id FROM task_attempts WHERE task_id=? AND task_revision=? "
                        "AND result_json IS NOT NULL ORDER BY attempt_no DESC LIMIT 1",
                        (task["id"], task["revision"]),
                    )
                    if run:
                        db.execute(
                            "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) "
                            "VALUES(?,'task.verify',?,?,?,'queued',?) "
                            "ON CONFLICT(dedupe_key) DO UPDATE SET state='queued',available_ms=excluded.available_ms "
                            "WHERE jobs.state IN ('done','failed')",
                            (
                                identity(),
                                task["id"],
                                "verify:" + run["id"],
                                encoded({"runId": run["id"]}),
                                now_ms(),
                            ),
                        )
            return {
                "taskId": task_id,
                "state": root["state"] if root["state"] in TERMINAL else "cancelling",
            }

        return await self.db.call(write, write=True)
