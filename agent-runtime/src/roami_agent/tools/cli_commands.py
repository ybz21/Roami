"""Invoke CLI capabilities only inside their admitted running tool context."""

import json

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import row


class CLICommands:
    def __init__(self, database, tools, journal):
        self.db, self.tools, self.journal = database, tools, journal
        self.invocations = set()

    async def call(self, name, payload, owner):
        if (
            not isinstance(payload, dict)
            or set(payload) != {"turnId", "toolCallId", "arguments"}
            or not isinstance(payload["arguments"], dict)
            or not all(isinstance(payload[key], str) for key in ("turnId", "toolCallId"))
        ):
            raise DomainError("INVALID_TOOL_ARGUMENTS")

        def context(db):
            turn = row(
                db,
                "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=? AND c.owner_id=? AND c.deleted_ms IS NULL AND t.state='running'",
                (payload["turnId"], owner),
            )
            call = row(
                db,
                "SELECT * FROM tool_calls WHERE turn_id=? AND idempotency_key=? AND state='running'",
                (payload["turnId"], payload["turnId"] + ":" + payload["toolCallId"]),
            )
            if (
                not turn
                or not call
                or call["tool_name"] != name
                or json.loads(call["arguments_json"]) != payload["arguments"]
            ):
                raise DomainError("ACTIVE_TOOL_CONTEXT_REQUIRED", 409)
            assert_context_admitted(db, turn)
            return turn, call

        turn, call = await self.db.call(context)
        if call["id"] in self.invocations:
            raise DomainError("TOOL_OUTCOME_UNKNOWN", 409)
        if len(self.invocations) >= 4096:
            raise DomainError("CLI_CONTEXT_CAPACITY", 503)
        self.invocations.add(call["id"])
        # The running parent bash owns the receipt, effects and context admission.
        task = await self.db.call(
            lambda db: row(
                db,
                "SELECT t.*,a.id AS execution_run_id FROM tasks t JOIN task_attempts a ON a.task_id=t.id WHERE a.native_branch_id=? AND t.owner_id=? ORDER BY a.rowid DESC LIMIT 1",
                (turn["branch_id"], owner),
            )
        )
        role = (
            "research"
            if task and (json.loads(task["intent_json"]).get("target") or {}).get("resourceOnly")
            else "worker"
            if task
            else "main"
        )
        origin = await self.journal.origin(turn)
        binding = {
            "owner": owner,
            "conversation": turn["conversation_id"],
            "turnId": turn["id"],
            "toolCallId": payload["toolCallId"],
            "assistantMessageId": call["assistant_message_id"],
            "originMessageId": origin["id"] if origin else None,
            "taskId": task["id"] if task else None,
            "runId": task["execution_run_id"] if task else None,
        }
        wire = {
            "function": {
                "name": "bash",
                "arguments": json.dumps(
                    {
                        "argv": [
                            "roami",
                            "agent",
                            "capability",
                            "call",
                            name,
                            "--input",
                            json.dumps(payload["arguments"]),
                        ]
                    }
                ),
            }
        }
        return await self.tools.invoke(wire, role, binding)
