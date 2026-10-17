"""Validated tool execution with durable receipts, progress and unknown outcomes."""

import asyncio
import math
import time

import httpx

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
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
        await self.db.call(
            lambda db: db.execute(
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
            ),
            write=True,
        )
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

            value = await self.tools.invoke(call, role, dict(binding, progress=progress))
            state = "succeeded"
        except (DomainError, TimeoutError, OSError, httpx.HTTPError) as exc:
            value = {"error": exc.code if isinstance(exc, DomainError) else "TOOL_FAILED"}
            state = "unknown" if value["error"] == "MCP_OUTCOME_UNKNOWN" else "failed"
            if state == "unknown":
                value.update(outcomeKnown=False, retryable=False)
        except asyncio.CancelledError:
            await self.db.call(
                lambda db: db.execute(
                    "UPDATE tool_calls SET state='unknown',updated_ms=? WHERE id=?",
                    (now_ms(), tool_id),
                ),
                write=True,
            )
            raise

        def finish(db):
            result_id = message(
                db,
                turn["conversation_id"],
                turn["branch_id"],
                "tool",
                {"text": encoded(value), "tool_call_id": call["id"]},
                turn_id=turn["id"],
            )
            db.execute(
                "UPDATE tool_calls SET state=?,result_message_id=?,updated_ms=? WHERE id=?",
                (state, result_id, now_ms(), tool_id),
            )
            event(
                db,
                turn["conversation_id"],
                "tool.completed",
                {"toolCallId": tool_id, "state": state},
                turn_id=turn["id"],
            )

        await self.db.call(finish, write=True)
        self.wakeup.set()
        if state == "unknown":
            raise DomainError("TOOL_OUTCOME_UNKNOWN")
        return value
