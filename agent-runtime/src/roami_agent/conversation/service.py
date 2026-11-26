"""Conversation intake, slash commands, status and interruption."""

import hashlib
import json

from roami_agent.conversation.model_commands import switch_model
from roami_agent.protocol.commands import COMMANDS
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import event, row
from roami_agent.storage.transcript_repository import owned


class ConversationService:
    def __init__(
        self,
        database,
        conversations,
        context,
        tasks,
        model,
        wakeup,
        turn_tasks,
        preempt=None,
        *,
        model_binding=None,
    ):
        self.db, self.conversations, self.context, self.tasks = (
            database,
            conversations,
            context,
            tasks,
        )
        self.model, self.wakeup, self.turn_tasks = model, wakeup, turn_tasks
        self.preempt = preempt
        self.model_binding = model_binding
        self.model_settings = None

    async def _provider(self, owner, cid):
        if self.model_binding is None:
            return None
        return await self.db.call(lambda db: self.model_binding(db, owner, cid))

    async def submit(self, owner, cid, request_key, text, attachment_ids=None, *, admission=None):
        native = await self.db.call(
            lambda db: row(
                db,
                "SELECT task_id FROM native_sessions WHERE conversation_id=? AND owner_id=? UNION ALL SELECT task_id FROM swarm_member_instances WHERE conversation_id=? AND owner_id=?",
                (cid, owner, cid, owner),
            )
        )
        if native:
            raise DomainError("NATIVE_SESSION_USE_TASK_CHANNEL", 409)
        provider = await self._provider(owner, cid)
        parts = text.strip().split(maxsplit=1)
        command, arguments = (parts[0], parts[1] if len(parts) > 1 else "") if parts else ("", "")
        if text.strip().startswith("/") and "\n" not in text.strip():
            if attachment_ids:
                raise DomainError("ATTACHMENTS_WITH_COMMAND")
            if admission is not None:
                raise DomainError("MESSAGE_METADATA_WITH_COMMAND")
            name = command[1:]
            if name not in {c["name"] for c in COMMANDS}:
                raise DomainError("UNKNOWN_COMMAND")
            if name not in {"compact", "model"} and arguments.strip():
                raise DomainError("UNEXPECTED_COMMAND_ARGUMENTS")
            await self.conversations.get(owner, cid)
            if name == "model":
                if provider:
                    model = arguments.strip()
                    provider.check_model(model)
                    return {
                        "kind": "model",
                        "model": provider.model,
                        "executor": provider.executor,
                        "conversationId": cid,
                    }
                self.model_settings.owner(owner)
                if not arguments.strip():
                    return {"kind": "ui_action", "action": "model", "conversationId": cid}
                return await switch_model(
                    self.model_settings, owner, cid, request_key, arguments.strip()
                )
            if name == "compact":
                if provider:
                    provider.check_compact()
                job = await self.context.request(owner, cid, request_key, arguments.strip())
                self.wakeup.set()
                return {"kind": "compaction", "operationId": job["id"], "state": job["state"]}
            if name == "stop":
                return await self.interrupt(owner, cid, request_key)
            if name == "help":
                return {"kind": "commands", "commands": COMMANDS}
            if name == "status":
                return await self.status(owner, cid)
            return {"kind": "ui_action", "action": name, "conversationId": cid}
        if not self.model.model and not provider:
            raise DomainError("MODEL_NOT_CONFIGURED", 503)
        result = await self.conversations.accept(
            owner, cid, request_key, text, attachment_ids, admission=admission
        )
        if self.preempt and not result.get("reused"):
            running = await self.db.call(
                lambda db: row(
                    db,
                    "SELECT id FROM turns WHERE branch_id=(SELECT branch_id FROM turns WHERE id=?) "
                    "AND state='running' AND id!=?",
                    (result["turnId"], result["turnId"]),
                )
            )
            if running:
                self.preempt(running["id"])
        self.wakeup.set()
        return {"kind": "message", **result}

    async def submit_scheduled(self, owner, cid, request_key, text, *, admission):
        provider = await self._provider(owner, cid)
        if not self.model.model and not provider:
            raise DomainError("MODEL_NOT_CONFIGURED", 503)
        result = await self.conversations.accept(
            owner, cid, request_key, text, admission=admission, scheduled=True
        )
        self.wakeup.set()
        return {"kind": "message", **result}

    async def status(self, owner, cid):
        plan = await self.context.project(owner, cid)
        provider = await self._provider(owner, cid)
        return {
            "kind": "status",
            "model": provider.model if provider else self.model.model,
            **(
                {"executor": provider.executor, "sessionId": provider.session_id}
                if provider
                else {}
            ),
            "conversationId": cid,
            "context": {k: v for k, v in plan.items() if k != "messages"},
            "tasks": await self.tasks.list(owner, cid),
            "writerBacklog": self.db.pending,
        }

    async def interrupt(self, owner, cid, request_key, *, expected_turn_id=None, pause_id=None):
        # A reversible pause preserves the original long-term goal authorization.
        kind = "control.pause" if pause_id else "control.stop"
        payload = (
            ["stop", cid, expected_turn_id, pause_id]
            if pause_id
            else ["stop", cid, expected_turn_id]
            if expected_turn_id
            else ["stop", cid]
        )
        digest = hashlib.sha256(encoded(payload).encode()).hexdigest()

        def write(db):
            c = owned(db, owner, cid)
            old = row(
                db,
                "SELECT * FROM requests WHERE owner_id=? AND request_key=?",
                (owner, request_key),
            )
            if old:
                if old["payload_sha256"] != digest:
                    raise DomainError("REQUEST_KEY_CONFLICT", 409)
                receipt = row(
                    db,
                    "SELECT payload_json FROM jobs WHERE kind=? AND aggregate_id=?",
                    (kind, old["id"]),
                )
                return json.loads(receipt["payload_json"])
            turn = row(
                db,
                "SELECT id,state FROM turns WHERE branch_id=? AND state IN ('running','queued') AND (? IS NULL OR id=?) "
                "ORDER BY CASE state WHEN 'running' THEN 0 ELSE 1 END,created_ms LIMIT 1",
                (c["active_branch_id"], expected_turn_id, expected_turn_id),
            )
            result = {"kind": "interrupt", "turnId": turn["id"] if turn else None}
            if turn and turn["state"] == "queued":
                db.execute(
                    "UPDATE turns SET state='interrupted',finished_ms=? WHERE id=?",
                    (now_ms(), turn["id"]),
                )
                db.execute(
                    "UPDATE jobs SET state='done' WHERE kind='turn.run' AND aggregate_id=? AND state='queued'",
                    (turn["id"],),
                )
                event(
                    db,
                    cid,
                    "turn.interrupted",
                    {"turnId": turn["id"], "error": "TURN_INTERRUPTED"},
                    turn_id=turn["id"],
                )
            rid = identity()
            db.execute(
                "INSERT INTO requests(id,owner_id,request_key,payload_sha256,conversation_id,accepted_ms) VALUES(?,?,?,?,?,?)",
                (rid, owner, request_key, digest, cid, now_ms()),
            )
            db.execute(
                "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) VALUES(?,?,?,?,?,'done',?)",
                (identity(), kind, rid, rid, encoded(result), now_ms()),
            )
            return result

        result = await self.db.call(write, write=True)
        handle = self.turn_tasks.get(result["turnId"])
        # The durable stop still wins over deferral while cancellation cleanup finishes.
        if handle and not handle.done() and not handle.cancelling():
            handle.cancel()
        return result
