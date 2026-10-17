"""Validated tool execution with durable receipts, progress and unknown outcomes."""

import asyncio
import math
import time

import httpx

from roami_agent.protocol.errors import DomainError, ToolCancellation
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import event, row
from roami_agent.storage.transcript_repository import message


class ToolGateway:
    def __init__(self, database, tools, wakeup):
        self.db, self.tools, self.wakeup = database, tools, wakeup

    async def invoke(self, turn, mid, call, role, binding):
        try:
            tool, args = self.tools.validate(call, role)
        except (DomainError, KeyError, TypeError):
            tool, args = None, {}
        tool_id = identity()

        def plan(db):
            assert_context_admitted(db, turn)
            db.execute(
                "INSERT INTO tool_calls(id,turn_id,assistant_message_id,tool_name,arguments_json,effect,state,idempotency_key,created_ms,updated_ms) "
                "VALUES(?,?,?,?,?,?,'planned',?,?,?)",
                (
                    tool_id,
                    turn["id"],
                    mid,
                    call["function"]["name"],
                    encoded(args),
                    tool.effect if tool else "read",
                    turn["id"] + ":" + call["id"],
                    now_ms(),
                    now_ms(),
                ),
            )

        await self.db.call(plan, write=True)
        try:
            await self.db.call(
                lambda db: db.execute(
                    "UPDATE tool_calls SET state='running' WHERE id=?", (tool_id,)
                ),
                write=True,
            )

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
            state = "succeeded"
        except (DomainError, TimeoutError, OSError, httpx.HTTPError) as exc:
            value = {"error": exc.code if isinstance(exc, DomainError) else "TOOL_FAILED"}
            state = (
                "unknown"
                if value["error"] in {"MCP_OUTCOME_UNKNOWN", "TOOL_OUTCOME_UNKNOWN"}
                else "failed"
            )
            if state == "unknown":
                value.update(outcomeKnown=False, retryable=False)
        except asyncio.CancelledError as exc:
            stopped = tool and (
                tool.cancellation_stops_execution
                or isinstance(exc, ToolCancellation)
                and exc.input_stopped
            )
            await self.db.call(
                lambda db: db.execute(
                    "UPDATE tool_calls SET state=?,updated_ms=? WHERE id=?",
                    (
                        "cancelled" if stopped else "unknown",
                        now_ms(),
                        tool_id,
                    ),
                ),
                write=True,
            )
            raise

        memory_ids = []
        if call["function"]["name"] in {"memory_get", "memory_search"}:
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
            if state == "succeeded" and call["function"]["name"] == "artifact_read":
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
            event(
                db,
                turn["conversation_id"],
                "tool.completed",
                {"toolCallId": tool_id, "state": committed_state},
                turn_id=turn["id"],
            )
            return committed_state, committed_value

        state, value = await self.db.call(finish, write=True)
        self.wakeup.set()
        if state == "unknown":
            raise DomainError("TOOL_OUTCOME_UNKNOWN")
        return value
