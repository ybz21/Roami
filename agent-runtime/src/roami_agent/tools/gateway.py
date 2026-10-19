"""Validated tool execution with durable receipts, progress and unknown outcomes."""

import asyncio
import math
import time

import httpx

from roami_agent.conversation.activity_events import activity_event as event
from roami_agent.protocol.errors import DomainError, ToolCancellation
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row
from roami_agent.storage.task_context import model_task_projection
from roami_agent.storage.transcript_repository import message


class ToolGateway:
    def __init__(self, database, tools, wakeup):
        self.db, self.tools, self.wakeup = database, tools, wakeup

    @staticmethod
    def activity(db, turn, binding, kind, payload):
        event(db, turn["conversation_id"], kind, payload, turn_id=turn["id"])
        task_id, seen = binding.get("taskId"), {turn["conversation_id"]}
        for _ in range(4):
            task = row(db, "SELECT * FROM tasks WHERE id=?", (task_id,)) if task_id else None
            if not task:
                break
            if task["origin_conversation_id"] not in seen:
                event(
                    db,
                    task["origin_conversation_id"],
                    "task.activity",
                    {**payload, "taskId": binding["taskId"]},
                    task_id=task["id"],
                )
                seen.add(task["origin_conversation_id"])
            task_id = task["parent_task_id"]

    async def invoke(self, turn, mid, call, role, binding):
        try:
            tool, args = self.tools.validate(call, role)
        except (DomainError, KeyError, TypeError):
            tool, args = None, {}
        tool_id = identity()
        operation_name = tool.name if tool else call["function"]["name"]

        def plan(db):
            assert_context_admitted(db, turn)
            db.execute(
                "INSERT INTO tool_calls(id,turn_id,assistant_message_id,tool_name,arguments_json,effect,state,idempotency_key,created_ms,updated_ms) "
                "VALUES(?,?,?,?,?,?,'planned',?,?,?)",
                (
                    tool_id,
                    turn["id"],
                    mid,
                    operation_name,
                    encoded(args),
                    tool.effect if tool else "read",
                    turn["id"] + ":" + call["id"],
                    now_ms(),
                    now_ms(),
                ),
            )

        await self.db.call(plan, write=True)
        try:

            def start(db):
                db.execute("UPDATE tool_calls SET state='running' WHERE id=?", (tool_id,))
                self.activity(
                    db,
                    turn,
                    binding,
                    "tool.started",
                    {
                        "toolCallId": tool_id,
                        "toolName": operation_name,
                        "state": "running",
                    },
                )

            await self.db.call(start, write=True)
            self.wakeup.set()

            progress_count, last_progress = 0, float("-inf")

            async def progress(current, total=None, _message=None):
                nonlocal progress_count, last_progress
                timestamp = time.monotonic()
                if progress_count >= 64 or timestamp - last_progress < 0.2:
                    return
                if (
                    not isinstance(current, (int, float))
                    or not math.isfinite(current)
                    or current < 0
                ):
                    return
                if total is not None and (
                    not isinstance(total, (int, float)) or not math.isfinite(total) or total < 0
                ):
                    return

                progress_count += 1
                last_progress = timestamp

                def write_progress(db):
                    if row(
                        db,
                        "SELECT id FROM turns WHERE id=? AND state='running' AND lease_epoch=?",
                        (turn["id"], turn["lease_epoch"]),
                    ):
                        event(
                            db,
                            turn["conversation_id"],
                            "tool.progress",
                            {"toolCallId": tool_id, "progress": current, "total": total},
                            turn_id=turn["id"],
                        )

                await self.db.call(write_progress, write=True)

            value = await self.tools.invoke(
                call, role, dict(binding, progress=progress, assistantMessageId=mid)
            )
            state = (
                "failed"
                if isinstance(value, dict)
                and isinstance(value.get("exitCode"), int)
                and value["exitCode"] != 0
                else "succeeded"
            )
        except (DomainError, TimeoutError, OSError, httpx.HTTPError) as exc:
            value = {"error": exc.code if isinstance(exc, DomainError) else "TOOL_FAILED"}
            if role == "main" and value["error"] in {
                "WORKSPACE_REQUIRED",
                "WORKSPACE_OUTSIDE_CONFIGURED_ROOTS",
            }:
                value["recovery"] = (
                    "Main has no shell workspace for this operation. Do not retry shell commands, "
                    "guess cwd or search projects to read a webpage. For bounded public lookups use delegate executor=native "
                    "with the current user's goal. For web-only reading use "
                    "target={kind:new_session,resourceOnly:true} with bounded routing; complex work goes to a professional executor with concrete routing evidence. For bounded file deliverables use "
                    "target={kind:new_session,directory:the_user_requested_directory}. "
                    "The worker loads the requested Skills and executes the task."
                )
            state = (
                "unknown"
                if value["error"] in {"MCP_OUTCOME_UNKNOWN", "TOOL_OUTCOME_UNKNOWN"}
                else "failed"
            )
            if state == "unknown":
                value.update(outcomeKnown=False, retryable=False)
            if role == "main" and value["error"] in {
                "INVALID_EXECUTION_DIRECTORY",
                "EXECUTION_DIRECTORY_UNAVAILABLE",
                "TASK_TARGET_REVIEW_REQUIRED",
            }:
                value["recovery"] = (
                    "The destination was rejected before task acceptance. Stop delegation for this turn. "
                    "Do not remove the directory, switch targets or invent a replacement to bypass the error. "
                    "Explain the rejected path and ask the user for a corrected existing destination."
                )
            if role == "main" and value["error"] == "TASK_CONTINUATION_ALREADY_REQUESTED":
                value["recovery"] = (
                    "Continuation is already queued on the original task. End this turn; do not poll or create a replacement task."
                )
            if role == "main" and value["error"] in {
                "ROUTING_EXECUTOR_CONFLICT",
                "ROUTING_EXPLICIT_UNAVAILABLE",
                "ROUTING_EXECUTOR_INTENT_REQUIRED",
            }:
                value["recovery"] = (
                    "Do not change or drop the rejected executor choice to bypass this error. "
                    "For a user-requested executor use routing.explicitExecutor with an exact userQuote; "
                    "omit the legacy top-level executor field. If unavailable, explain and ask the user without dispatching."
                )
            if role == "main" and value["error"] in {
                "TASK_SESSION_BINDING_REQUIRED",
                "TASK_OUTCOME_UNRESOLVED",
            }:
                value["recovery"] = (
                    "The original execution is unresolved. Do not message guessed sessions based on project membership "
                    "or create a replacement task. Report the unresolved state and wait for actual stop evidence."
                )
        except asyncio.CancelledError as exc:
            stopped = tool and (
                tool.cancellation_stops_execution
                or isinstance(exc, ToolCancellation)
                and exc.input_stopped
            )

            def cancelled(db):
                state = "cancelled" if stopped else "unknown"
                db.execute(
                    "UPDATE tool_calls SET state=?,updated_ms=? WHERE id=?",
                    (state, now_ms(), tool_id),
                )
                self.activity(
                    db,
                    turn,
                    binding,
                    "tool.completed",
                    {"toolCallId": tool_id, "toolName": operation_name, "state": state},
                )

            await self.db.call(cancelled, write=True)
            self.wakeup.set()
            raise

        memory_ids = []
        if operation_name in {"memory_get", "memory_search"}:
            hits = (
                value
                if isinstance(value, list)
                else value.get("hits", [value])
                if isinstance(value, dict)
                else []
            )
            memory_ids = [
                hit["id"]
                for hit in hits
                if isinstance(hit, dict) and isinstance(hit.get("id"), str)
            ][:8]

        def finish(db):
            committed_value, committed_state, committed_memories = value, state, memory_ids
            if state == "succeeded" and operation_name == "task_status":
                committed_value = model_task_projection(db, binding["owner"], value)
            if state == "succeeded" and operation_name == "artifact_read":
                source = row(
                    db,
                    "SELECT sha256 FROM artifacts WHERE id=? AND owner_id=? AND deleted_ms IS NULL",
                    (args["id"], binding["owner"]),
                )
                if not source or row(
                    db,
                    "SELECT 1 FROM memory_tombstones WHERE owner_id=? AND source_fingerprint=?",
                    (binding["owner"], source["sha256"]),
                ):
                    committed_value, committed_state = (
                        {"error": "ARTIFACT_SOURCE_UNAVAILABLE"},
                        "failed",
                    )
            if (
                state == "succeeded"
                and memory_ids
                and any(
                    not row(
                        db,
                        "SELECT id FROM memory_records WHERE id=? AND owner_id=? AND state='active'",
                        (memory_id, binding["owner"]),
                    )
                    for memory_id in memory_ids
                )
            ):
                committed_value, committed_state, committed_memories = (
                    {"error": "MEMORY_SOURCE_CHANGED"},
                    "failed",
                    [],
                )
            result_id = message(
                db,
                turn["conversation_id"],
                turn["branch_id"],
                "tool",
                {
                    "text": encoded(committed_value),
                    "tool_call_id": call["id"],
                    **({"memoryIds": committed_memories} if committed_memories else {}),
                },
                turn_id=turn["id"],
            )
            db.execute(
                "UPDATE tool_calls SET state=?,result_message_id=?,updated_ms=? WHERE id=?",
                (committed_state, result_id, now_ms(), tool_id),
            )
            self.activity(
                db,
                turn,
                binding,
                "tool.completed",
                {
                    "toolCallId": tool_id,
                    "toolName": operation_name,
                    "state": committed_state,
                },
            )
            return committed_state, committed_value

        state, value = await self.db.call(finish, write=True)
        self.wakeup.set()
        if state == "unknown":
            raise DomainError("TOOL_OUTCOME_UNKNOWN")
        return value
