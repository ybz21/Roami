"""Read-only, content-free execution waterfalls over durable runtime evidence."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.storage.database import row, rows


class ExecutionTraces:
    def __init__(self, database):
        self.db = database

    async def get(self, owner, *, turn_id=None, task_id=None, chrome=False):
        if bool(turn_id) == bool(task_id):
            raise DomainError("TRACE_ONE_TARGET_REQUIRED")
        return await self.db.call(
            lambda db: read_trace(db, owner, turn_id=turn_id, task_id=task_id, chrome=chrome)
        )


def origin_turn(db, owner, turn_id=None, task_id=None):
    seen = set()
    while len(seen) < 64:
        if task_id:
            if "task:" + task_id in seen:
                raise DomainError("TRACE_LINK_CYCLE", 409)
            seen.add("task:" + task_id)
            source = row(
                db,
                "SELECT m.turn_id,t.id,t.created_ms,t.origin_conversation_id,t.origin_branch_id,t.parent_task_id FROM tasks t "
                "JOIN messages m ON m.id=t.origin_message_id "
                "JOIN conversations c ON c.id=t.origin_conversation_id "
                "WHERE t.id=? AND t.owner_id=? AND c.deleted_ms IS NULL",
                (task_id, owner),
            )
            if not source:
                raise DomainError("TRACE_NOT_FOUND", 404)
            if source["parent_task_id"]:
                task_id = source["parent_task_id"]
                continue
            if source["turn_id"] is None:
                return {
                    "id": source["id"],
                    "node_kind": "task",
                    "request_id": None,
                    "created_ms": source["created_ms"],
                    "conversation_id": source["origin_conversation_id"],
                    "branch_id": source["origin_branch_id"],
                }
            turn_id, task_id = source["turn_id"], None
        turn = row(
            db,
            "SELECT t.* FROM turns t JOIN conversations c ON c.id=t.conversation_id "
            "WHERE t.id=? AND c.owner_id=? AND c.deleted_ms IS NULL",
            (turn_id, owner),
        )
        if not turn:
            raise DomainError("TRACE_NOT_FOUND", 404)
        if turn_id in seen:
            raise DomainError("TRACE_LINK_CYCLE", 409)
        seen.add(turn_id)
        native = row(
            db,
            "SELECT a.task_id FROM task_attempts a JOIN tasks t ON t.id=a.task_id "
            "WHERE a.native_branch_id=? AND t.owner_id=? ORDER BY a.attempt_no DESC LIMIT 1",
            (turn["branch_id"], owner),
        )
        completion = row(
            db,
            "SELECT json_extract(payload_json,'$.completion.taskId') AS task_id "
            "FROM jobs WHERE kind='turn.run' AND aggregate_id=?",
            (turn_id,),
        )
        task_id = native["task_id"] if native else completion["task_id"] if completion else None
        if not task_id:
            return turn
    raise DomainError("TRACE_LINK_LIMIT", 409)


def trace_nodes(db, owner, root_id, kind="turn"):
    nodes = rows(
        db,
        "WITH RECURSIVE nodes(kind,id) AS (VALUES(?,?) "
        "UNION SELECT 'task',t.id FROM nodes n JOIN messages m ON n.kind='turn' AND m.turn_id=n.id "
        "JOIN tasks t ON t.origin_message_id=m.id WHERE t.owner_id=? "
        "UNION SELECT 'task',t.id FROM nodes n JOIN tasks t ON n.kind='task' AND t.parent_task_id=n.id "
        "WHERE t.owner_id=? "
        "UNION SELECT 'turn',u.id FROM nodes n JOIN task_attempts a ON n.kind='task' AND a.task_id=n.id "
        "JOIN turns u ON u.branch_id=a.native_branch_id "
        "UNION SELECT 'turn',j.aggregate_id FROM nodes n JOIN jobs j ON n.kind='task' "
        "AND j.kind='turn.run' AND json_extract(j.payload_json,'$.completion.taskId')=n.id "
        "LIMIT 2049) SELECT * FROM nodes",
        (kind, root_id, owner, owner),
    )
    if len(nodes) > 2048:
        raise DomainError("TRACE_LINK_LIMIT", 409)
    return nodes


def read_trace(db, owner, *, turn_id=None, task_id=None, chrome=False):
    root = origin_turn(db, owner, turn_id, task_id)
    nodes = trace_nodes(db, owner, root["id"], root.get("node_kind", "turn"))
    turns, tasks = {}, {}
    for node in nodes:
        table = "turns" if node["kind"] == "turn" else "tasks"
        item = row(db, f"SELECT * FROM {table} WHERE id=?", (node["id"],))
        (turns if node["kind"] == "turn" else tasks)[node["id"]] = item
    spans, attempts, completions = [], {}, {}
    timestamp = now_ms()

    def span(identifier, name, parent, start, end, state, **attributes):
        if start is None:
            return
        if len(spans) >= 10000:
            raise DomainError("TRACE_SPAN_LIMIT", 409)
        spans.append(
            {
                "spanId": identifier,
                "parentSpanId": parent,
                "name": name,
                "startedMs": start,
                "finishedMs": end,
                "durationMs": max(0, end - start) if end is not None else None,
                "state": state,
                "attributes": attributes,
            }
        )

    for task in tasks.values():
        for attempt in rows(
            db, "SELECT * FROM task_attempts WHERE task_id=? ORDER BY attempt_no", (task["id"],)
        ):
            attempts[attempt["id"]] = attempt
    for turn in turns.values():
        job = row(
            db,
            "SELECT json_extract(payload_json,'$.completion') AS completion "
            "FROM jobs WHERE kind='turn.run' AND aggregate_id=?",
            (turn["id"],),
        )
        if job and job["completion"]:
            completions[turn["id"]] = json.loads(job["completion"])

    for attempt in attempts.values():
        task = tasks[attempt["task_id"]]
        source = row(db, "SELECT turn_id FROM messages WHERE id=?", (task["origin_message_id"],))
        source_turn = source["turn_id"] if source else None
        parent = "trace:" + root["id"]
        run_id = "run:" + attempt["id"]
        span(
            run_id,
            "executor." + attempt["executor_kind"],
            parent,
            attempt["started_ms"],
            attempt["finished_ms"],
            attempt["state"],
            taskId=task["id"],
            runId=attempt["id"],
            taskState=task["state"],
            revision=attempt["task_revision"],
            observationUnit="turn" if attempt["executor_kind"] == "cli" else "native_run",
            internalStepsObservable=attempt["executor_kind"] == "native",
            sourceTurnId=source_turn,
        )
        if attempt["attempt_no"] == 1:
            span(
                "task-queue:" + attempt["id"],
                "task.queue",
                parent,
                task["created_ms"],
                attempt["started_ms"],
                "completed" if attempt["started_ms"] else "queued",
                taskId=task["id"],
            )
        prepared = row(
            db,
            "SELECT MIN(created_ms) AS ms FROM events WHERE kind='task.workspace_prepared' "
            "AND json_extract(payload_json,'$.runId')=?",
            (attempt["id"],),
        )["ms"]
        if prepared is not None:
            span(
                "prepare:" + attempt["id"],
                "executor.prepare",
                run_id,
                attempt["started_ms"],
                prepared,
                "completed",
                runId=attempt["id"],
            )
        verification = row(
            db,
            "SELECT id FROM jobs WHERE kind='task.verify' AND json_extract(payload_json,'$.runId')=?",
            (attempt["id"],),
        )
        if verification:
            reported = row(
                db,
                "SELECT MIN(created_ms) AS ms FROM events WHERE kind='task.result' AND json_extract(payload_json,'$.runId')=?",
                (attempt["id"],),
            )["ms"]
            verified = row(
                db,
                "SELECT MIN(created_ms) AS ms FROM events WHERE kind IN ('task.succeeded','task.failed','task.waiting_user','task.cancelled','task.interrupted') AND json_extract(payload_json,'$.runId')=?",
                (attempt["id"],),
            )["ms"]
            span(
                "verify:" + attempt["id"],
                "task.verification_and_queue",
                "trace:" + root["id"],
                reported,
                verified,
                "completed" if verified else "queued",
                runId=attempt["id"],
                taskState=task["state"],
            )

    for turn in turns.values():
        tid = turn["id"]
        native = next(
            (a for a in attempts.values() if a["native_branch_id"] == turn["branch_id"]), None
        )
        completion = completions.get(tid)
        parent_run = native["id"] if native else completion.get("runId") if completion else None
        span(
            "turn:" + tid,
            "agent.report" if completion else "agent.worker" if native else "agent.main",
            "run:" + parent_run if native else "trace:" + root["id"],
            turn["created_ms"],
            turn["finished_ms"],
            turn["state"],
            turnId=tid,
            requestId=turn["request_id"],
            conversationId=turn["conversation_id"],
            linkedRunId=parent_run if completion else None,
        )
        manifests = rows(
            db, "SELECT * FROM prompt_manifests WHERE turn_id=? ORDER BY attempt_no", (tid,)
        )
        message_spans = {}
        for manifest in manifests:
            parts = json.loads(manifest["parts_json"])
            timing = parts.get("timing") or {}
            mid = parts.get("responseMessageId")
            model_id = "model:" + manifest["id"]
            if mid:
                message_spans[mid] = model_id
            terminal = row(
                db,
                "SELECT MIN(created_ms) AS ms FROM events WHERE message_id=? "
                "AND kind IN ('message.tool_calls','message.completed')",
                (mid,),
            )
            started = timing.get("modelStartedMs", manifest["created_ms"])
            finished = timing.get("modelFinishedMs", terminal["ms"])
            state = timing.get("state", "completed" if finished else "unknown")
            usage = json.loads(manifest["usage_json"]) if manifest["usage_json"] else {}
            tokens = {
                key: usage.get(key)
                for key in ("inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens")
            }
            span(
                model_id,
                "model.request",
                "turn:" + tid,
                started,
                finished,
                state,
                turnId=tid,
                model=manifest["model_key"],
                role=parts.get("role"),
                attempt=manifest["attempt_no"],
                observationUnit="request",
                timingSource="measured" if timing.get("modelStartedMs") else "message_lifecycle",
                elapsedMs=timing.get("modelDurationMs"),
                firstTextMs=timing.get("firstTextMs"),
                providerEvents=timing.get("providerEvents", []),
                requestAttempts=usage.get("requestAttempts"),
                errorCode=timing.get("errorCode"),
                tokens=tokens,
                context=parts.get("modelContext"),
                limits=parts.get("requestLimits"),
            )
            if "contextStartedMs" in timing:
                context_start = timing["contextStartedMs"]
                span(
                    "context:" + manifest["id"],
                    "context.build",
                    "turn:" + tid,
                    context_start,
                    context_start + timing["contextDurationMs"],
                    "completed",
                )
        if manifests:
            first = json.loads(manifests[0]["parts_json"]).get("timing") or {}
            measured = "contextStartedMs" in first
            span(
                "turn-queue:" + tid,
                "worker.prepare"
                if native
                else "turn.queue"
                if measured
                else "turn.admission_and_context",
                "turn:" + tid,
                turn["created_ms"],
                first.get("contextStartedMs", manifests[0]["created_ms"]),
                "completed",
                timingSource="measured" if measured else "message_lifecycle",
            )
        for deferred in rows(
            db,
            "SELECT id,created_ms FROM events WHERE turn_id=? AND kind='turn.deferred' ORDER BY id",
            (tid,),
        ):
            resumed = next(
                (
                    json.loads(m["parts_json"])
                    .get("timing", {})
                    .get("contextStartedMs", m["created_ms"])
                    for m in manifests
                    if m["created_ms"] >= deferred["created_ms"]
                ),
                None,
            )
            wait_end = resumed or turn["finished_ms"]
            span(
                "deferred:" + str(deferred["id"]),
                "turn.rescheduled",
                "turn:" + tid,
                deferred["created_ms"],
                wait_end,
                "resumed" if resumed is not None else "interrupted" if wait_end else "queued",
                reason="NEW_USER_INTENT",
            )
        for tool in rows(db, "SELECT * FROM tool_calls WHERE turn_id=?", (tid,)):
            terminal = tool["state"] not in {"running", "planned"}
            span(
                "tool:" + tool["id"],
                "tool." + tool["tool_name"],
                "turn:" + tid,
                tool["created_ms"],
                tool["updated_ms"] if terminal else None,
                tool["state"],
                toolCallId=tool["id"],
                toolName=tool["tool_name"],
                effect=tool["effect"],
                turnId=tid,
                causedBySpanId=message_spans.get(tool["assistant_message_id"]),
            )
    spans.sort(key=lambda item: (item["startedMs"], item["spanId"]))
    if len(spans) > 10000:
        raise DomainError("TRACE_SPAN_LIMIT", 409)
    active = any(
        t["state"] in {"queued", "preparing", "running", "verifying", "cancelling"}
        for t in tasks.values()
    ) or any(
        s["state"] in {"queued", "preparing", "running", "starting", "stopping"} for s in spans
    )
    end = None if active else max(s["finishedMs"] or s["startedMs"] for s in spans)
    span(
        "trace:" + root["id"],
        "agent.execution",
        None,
        root["created_ms"],
        end,
        "running" if active else "settled",
    )
    spans.sort(key=lambda item: (item["startedMs"], item["spanId"]))
    first_text = row(
        db,
        "SELECT MIN(created_ms) AS ms FROM events WHERE turn_id=? AND kind='message.delta'",
        (root["id"],),
    )["ms"]
    result = {
        "schemaVersion": 1,
        "traceId": root["id"],
        "requestId": root["request_id"],
        "rootTurnId": root["id"] if root.get("node_kind", "turn") == "turn" else None,
        "observedAtMs": timestamp,
        "startedMs": root["created_ms"],
        "finishedMs": end,
        "summary": {
            "durationMs": max(0, (end or timestamp) - root["created_ms"]),
            "firstCommittedTextMs": first_text - root["created_ms"] if first_text else None,
            "active": active,
            "hasFailures": any(s["state"] == "failed" for s in spans),
            "hasUnknown": any(s["state"] == "unknown" for s in spans),
            "taskStates": {t["id"]: t["state"] for t in tasks.values()},
            "modelCalls": sum(s["name"] == "model.request" for s in spans),
            "toolCalls": sum(s["name"].startswith("tool.") for s in spans),
            "durationSumsMayOverlap": True,
        },
        "spans": spans,
        "coverage": {
            "start": "python_turn_admission",
            "end": "committed_main_reply",
            "browserPaint": False,
            "goIngress": False,
            "externalAgentInternals": False,
            "contentIncluded": False,
        },
    }
    if chrome:
        return chrome_trace(result)
    return result


def chrome_trace(trace):
    events = []
    lanes = {}
    for span in trace["spans"]:
        attributes = span["attributes"]
        lane = attributes.get("turnId", attributes.get("runId", span["spanId"]))
        if lane not in lanes:
            lanes[lane] = len(lanes) + 1
            events.append(
                {
                    "ph": "M",
                    "name": "thread_name",
                    "pid": 1,
                    "tid": lanes[lane],
                    "args": {"name": lane},
                }
            )
        args = dict(attributes, state=span["state"], parentSpanId=span["parentSpanId"])
        event = {
            "name": span["name"],
            "cat": span["name"].split(".")[0],
            "pid": 1,
            "tid": lanes[lane],
            "ts": span["startedMs"] * 1000,
            "args": args,
        }
        if span["finishedMs"] is None:
            event.update(ph="i", s="t")
        else:
            event.update(ph="X", dur=span["durationMs"] * 1000)
        events.append(event)
    return {"traceEvents": events, "displayTimeUnit": "ms", "roami": dict(trace, spans=None)}
