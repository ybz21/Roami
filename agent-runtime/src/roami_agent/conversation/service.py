"""Conversation intake, slash commands, status and interruption."""

import hashlib
import json

from roami_agent.protocol.commands import COMMANDS
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import event, row
from roami_agent.storage.transcript_repository import owned


class ConversationService:
    def __init__(
        self, database, conversations, context, tasks, model, wakeup, turn_tasks, preempt=None
    ):
        self.db, self.conversations, self.context, self.tasks = (
            database,
            conversations,
            context,
            tasks,
        )
        self.model, self.wakeup, self.turn_tasks = model, wakeup, turn_tasks
        self.preempt = preempt

    async def submit(self, owner, cid, request_key, text, attachment_ids=None):
        parts = text.strip().split(maxsplit=1)
        command, arguments = (parts[0], parts[1] if len(parts) > 1 else "") if parts else ("", "")
        if text.strip().startswith("/") and "\n" not in text.strip():
            if attachment_ids:
                raise DomainError("ATTACHMENTS_WITH_COMMAND")
            name = command[1:]
            if name not in {c["name"] for c in COMMANDS}:
                raise DomainError("UNKNOWN_COMMAND")
            if name != "compact" and arguments.strip():
                raise DomainError("UNEXPECTED_COMMAND_ARGUMENTS")
            await self.conversations.get(owner, cid)
            if name == "compact":
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
        if not self.model.model:
            raise DomainError("MODEL_NOT_CONFIGURED", 503)
        result = await self.conversations.accept(owner, cid, request_key, text, attachment_ids)
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

    async def status(self, owner, cid):
        plan = await self.context.project(owner, cid)
        return {
            "kind": "status",
            "model": self.model.model,
            "conversationId": cid,
            "context": {k: v for k, v in plan.items() if k != "messages"},
            "tasks": await self.tasks.list(owner, cid),
            "writerBacklog": self.db.pending,
        }

    async def interrupt(self, owner, cid, request_key):
        digest = hashlib.sha256(encoded(["stop", cid]).encode()).hexdigest()

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
                    "SELECT payload_json FROM jobs WHERE kind='control.stop' AND aggregate_id=?",
                    (old["id"],),
                )
                return json.loads(receipt["payload_json"])
            turn = row(
                db,
                "SELECT id,state FROM turns WHERE branch_id=? AND state IN ('running','queued') "
                "ORDER BY CASE state WHEN 'running' THEN 0 ELSE 1 END,created_ms LIMIT 1",
                (c["active_branch_id"],),
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
                "INSERT INTO jobs(id,kind,aggregate_id,dedupe_key,payload_json,state,available_ms) VALUES(?,'control.stop',?,?,?,'done',?)",
                (identity(), rid, rid, encoded(result), now_ms()),
            )
            return result

        result = await self.db.call(write, write=True)
        handle = self.turn_tasks.get(result["turnId"])
        if handle:
            handle.cancel()
        return result
