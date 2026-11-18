"""Signed turn-scoped native Main calls retain the original host tool gateway."""

import asyncio
import hashlib
import hmac
import json
import os
import re
import shlex
import tempfile

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.context_admission import assert_context_admitted
from roami_agent.storage.database import event, row
from roami_agent.storage.transcript_repository import message
from roami_agent.tools.professional_capabilities import ProfessionalCapabilities


class NativeMainCapabilities(ProfessionalCapabilities):
    @staticmethod
    def admitted(db, context, owner):
        turn = row(
            db,
            "SELECT t.*,c.owner_id FROM turns t JOIN conversations c ON c.id=t.conversation_id "
            "JOIN project_okr_mains m ON m.conversation_id=c.id AND m.owner_id=c.owner_id "
            "JOIN project_okr_main_providers p ON p.conversation_id=c.id AND p.owner_id=c.owner_id "
            "AND p.project_id=m.project_id WHERE t.id=? AND c.owner_id=? AND c.deleted_ms IS NULL "
            "AND t.state='running' AND t.lease_epoch=? AND c.id=? AND p.project_id=? "
            "AND p.generation=? AND p.provider_id=? "
            "AND NOT EXISTS(SELECT 1 FROM project_okr_main_providers newer "
            "WHERE newer.owner_id=p.owner_id AND newer.project_id=p.project_id "
            "AND newer.generation>p.generation)",
            (
                context["turnId"],
                owner,
                context["leaseEpoch"],
                context["conversationId"],
                context["projectId"],
                context["generation"],
                context["providerId"],
            ),
        )
        if not turn:
            raise DomainError("ACTIVE_MAIN_CONTEXT_REQUIRED", 409)
        assert_context_admitted(db, turn)
        return turn

    async def brief(self, binding, turn):
        context = {
            "kind": "project_main",
            "owner": binding["owner_id"],
            "projectId": binding["project_id"],
            "conversationId": binding["conversation_id"],
            "turnId": turn["id"],
            "leaseEpoch": turn["lease_epoch"],
            "generation": binding["generation"],
            "providerId": binding["provider_id"],
        }
        await self.db.call(lambda db: self.admitted(db, context, context["owner"]))
        context["signature"] = self.signature(context)
        name = hashlib.sha256(encoded(context).encode()).hexdigest() + ".json"
        path = self.private_directory() / name
        descriptor, temporary = tempfile.mkstemp(prefix=".main-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w") as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(encoded(context))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        discover = shlex.quote(encoded({"query": "swarm", "limit": 20}))
        return (
            "\n\nRegistered Main capabilities use this ORIGINAL running Main turn, not a worker. "
            "Discover Main operation names and input schemas through the signed tool_list call below. "
            "Call managed Swarm, task, memory and project operations through this signed context:\n"
            "```bash\n"
            f"ROAMI_BIN={shlex.quote(self.runtime.settings.cli_bin)}\n"
            f"ROAMI_MAIN_CONTEXT={shlex.quote(str(path))}\n"
            '"$ROAMI_BIN" agent capability call tool_list --context "$ROAMI_MAIN_CONTEXT" '
            f"--call discover-swarm --input {discover}\n"
            '"$ROAMI_BIN" agent capability call CAPABILITY_NAME --context "$ROAMI_MAIN_CONTEXT" '
            "--call STABLE_REQUEST_ID --input 'EXACT_JSON_ARGUMENTS'\n"
            "```\n"
            "Use discovered capability names, never placeholders. Keep the same request ID and "
            "arguments when recovering an uncertain response; unknown outcomes cannot be replayed. "
            "Each response includes toolCallId: use that registered ID, not requestId, when a "
            "checkpoint requires failedToolCallId. "
            "The context is private and expires when this turn stops or its lease/provider changes. "
            "Do not export it, invent task/run IDs, use human swarm say to impersonate Main, or "
            "bypass the registered verification and publication rules. Return your final answer "
            "normally; the host owns final reply delivery, so do not call reply here.\n"
        )

    async def invoke(self, name, payload, owner):
        if self.closed:
            raise DomainError("RUNTIME_CLOSED", 503)
        if (
            not isinstance(payload, dict)
            or set(payload) != {"executionContext", "requestId", "arguments"}
            or not isinstance(payload["arguments"], dict)
            or not isinstance(payload["requestId"], str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", payload["requestId"])
        ):
            raise DomainError("INVALID_TOOL_ARGUMENTS")
        context = payload["executionContext"]
        strings = {
            "kind",
            "owner",
            "projectId",
            "conversationId",
            "turnId",
            "providerId",
            "signature",
        }
        if (
            not isinstance(context, dict)
            or set(context) != strings | {"leaseEpoch", "generation"}
            or any(not isinstance(context[k], str) or not context[k] for k in strings)
            or context["kind"] != "project_main"
            or context["owner"] != owner
            or type(context["leaseEpoch"]) is not int
            or type(context["generation"]) is not int
            or context["generation"] < 1
            or not re.fullmatch(r"[a-f0-9]{64}", context["signature"])
            or not hmac.compare_digest(
                context["signature"],
                self.signature({k: v for k, v in context.items() if k != "signature"}),
            )
        ):
            raise DomainError("ACTIVE_MAIN_CONTEXT_REQUIRED", 409)
        if name == "reply":
            raise DomainError("TOOL_UNAVAILABLE", 409)
        request_id = payload["requestId"]
        call_id = (
            "native-main-"
            + hashlib.sha256((context["turnId"] + ":" + request_id).encode()).hexdigest()
        )
        key = "capability:" + call_id
        wire = {
            "id": call_id,
            "function": {"name": name, "arguments": encoded(payload["arguments"])},
        }

        def plan(db):
            turn = self.admitted(db, context, owner)
            tool, _ = self.runtime.tools.validate(wire, "main")
            if tool.name == "reply":
                raise DomainError("TOOL_UNAVAILABLE", 409)
            previous = row(
                db, "SELECT payload_json FROM events WHERE event_key=?", (key + ":start",)
            )
            if previous:
                start = json.loads(previous["payload_json"])
                if start["name"] != name or start["arguments"] != payload["arguments"]:
                    raise DomainError("CAPABILITY_REQUEST_CONFLICT", 409)
                result = row(
                    db, "SELECT payload_json FROM events WHERE event_key=?", (key + ":result",)
                )
                if not result:
                    raise DomainError("TOOL_OUTCOME_UNKNOWN", 409)
                return turn, None, json.loads(result["payload_json"])
            assistant = row(
                db,
                "SELECT id FROM messages WHERE turn_id=? AND role='assistant' AND status='streaming' AND deleted_ms IS NULL ORDER BY seq DESC LIMIT 1",
                (turn["id"],),
            )
            if not assistant:
                raise DomainError("ACTIVE_MAIN_CONTEXT_REQUIRED", 409)
            calls = [{**wire, "type": "function"}]
            mid = message(
                db,
                turn["conversation_id"],
                turn["branch_id"],
                "assistant",
                {"text": "", "tool_calls": calls},
                turn_id=turn["id"],
            )
            event(
                db,
                turn["conversation_id"],
                "message.tool_calls",
                {"messageId": mid, "calls": calls},
                turn_id=turn["id"],
                message_id=mid,
            )
            event(
                db,
                turn["conversation_id"],
                "capability.started",
                {"name": name, "arguments": payload["arguments"], "requestId": request_id},
                key=key + ":start",
                turn_id=turn["id"],
            )
            return turn, mid, None

        turn, mid, previous = await self.db.call(plan, write=True)
        if previous is not None:
            return previous
        origin = await self.runtime.journal.origin(turn)
        binding = {
            "owner": owner,
            "conversation": turn["conversation_id"],
            "turnId": turn["id"],
            "leaseEpoch": turn["lease_epoch"],
            "toolCallId": call_id,
            "assistantMessageId": mid,
            "originMessageId": origin["id"] if origin else None,
            "taskId": None,
            "runId": None,
        }
        operation = asyncio.create_task(
            self.runtime.gateway.invoke(turn, mid, wire, "main", binding)
        )
        try:
            while not operation.done():
                await asyncio.wait({operation}, timeout=0.25)
                await self.db.call(lambda db: self.admitted(db, context, owner))
            await operation
        except DomainError:
            # The gateway may have persisted a definitive rejection before raising.
            pass
        finally:
            if not operation.done():
                operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)

        def finish(db):
            stored = row(
                db,
                "SELECT t.state,json_extract(native_content(m.content_json),'$.text') AS result FROM tool_calls t LEFT JOIN messages m ON m.id=t.result_message_id WHERE t.idempotency_key=?",
                (turn["id"] + ":" + call_id,),
            )
            result = {
                "state": stored["state"]
                if stored
                and stored["state"] in {"succeeded", "failed", "cancelled"}
                and stored["result"]
                else "unknown",
                "result": json.loads(stored["result"])
                if stored and stored["result"]
                else {"error": "TOOL_OUTCOME_UNKNOWN"},
                "requestId": request_id,
                "toolCallId": call_id,
                "finishedMs": now_ms(),
            }
            event(
                db,
                turn["conversation_id"],
                "capability.completed",
                result,
                key=key + ":result",
                turn_id=turn["id"],
            )
            return result

        result = await self.db.call(finish, write=True)
        self.runtime.wakeup.set()
        return result
