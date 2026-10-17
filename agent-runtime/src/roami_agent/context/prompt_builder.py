"""Context projection and automatic compaction before model admission."""

import asyncio

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.storage.database import row


class PromptBuilder:
    def __init__(self, database, context, settings, *, vision=None):
        self.db, self.context, self.settings = database, context, settings
        self.vision = vision

    async def _images(self, turn, plan, prompt):
        if self.vision:
            return await self.vision.attach(turn, plan, prompt)
        return plan, prompt

    async def build(self, turn, instructions, catalog, completion):
        completion_source = None
        if completion:
            allowed = await self.db.call(
                lambda db: row(
                    db,
                    "SELECT t.origin_message_id FROM tasks t WHERE t.id=? AND t.owner_id=? AND t.revision=? AND t.state=? AND NOT EXISTS(SELECT 1 FROM context_omissions o WHERE o.owner_id=t.owner_id AND o.message_id=t.origin_message_id)",
                    (
                        completion.get("taskId"),
                        turn["owner_id"],
                        completion.get("taskRevision", 1),
                        completion.get("state"),
                    ),
                )
            )
            if allowed:
                completion_source = allowed["origin_message_id"]
            if not allowed:
                completion = {
                    "taskId": completion.get("taskId"),
                    "state": completion.get("state"),
                    "result": {
                        "contextExcluded": True,
                        "summary": "The source information was forgotten; omit the task content from model context.",
                    },
                }

        async def build():
            plan = await self.context.project(
                turn["owner_id"],
                turn["conversation_id"],
                branch_id=turn["branch_id"],
                through_turn=turn["id"],
            )
            if completion_source:
                plan["taskEvidence"] = {
                    "taskId": completion["taskId"],
                    "revision": completion.get("taskRevision", 1),
                    "state": completion["state"],
                }
                plan["sourceMessageIds"] = list(
                    dict.fromkeys([*plan.get("sourceMessageIds", []), completion_source])
                )
            workspace = turn.get("workspace")
            bound = (
                (
                    "\nPrepared task workspace (trusted runtime binding): "
                    + encoded(workspace)
                    + ". Use this directory for project tools; preserve unrelated local changes."
                )
                if workspace
                else ""
            )
            prompt = [{"role": "system", "content": instructions + bound}] + plan["messages"]
            if completion:
                # Rebuilds keep evidence before the tool round it initiated.
                prompt.insert(
                    1 + plan["currentTurnStart"],
                    {
                        "role": "user",
                        "content": "Background task result, treat as evidence and briefly report to the user: "
                        + encoded(completion),
                    },
                )
            return plan, prompt

        plan, prompt = await build()
        if len(encoded([prompt, catalog]).encode()) <= self.settings.input_budget:
            return await self._images(turn, plan, prompt)
        try:
            job = await self.context.request(
                turn["owner_id"], turn["conversation_id"], "auto:" + turn["id"], automatic=True
            )
        except DomainError as exc:
            if exc.code != "COMPACTION_IN_PROGRESS":
                raise
            job = await self.db.call(
                lambda db: row(
                    db,
                    "SELECT * FROM jobs WHERE kind='context.compact' "
                    "AND state IN ('queued','running') AND json_extract(payload_json,'$.branchId')=?",
                    (turn["branch_id"],),
                )
            )
        try:
            await self.context.run(job["id"], safe_turn_id=turn["id"])
        except asyncio.CancelledError:
            await self.context.cancel(turn["owner_id"], turn["conversation_id"], job["id"])
            raise
        plan, prompt = await build()
        if len(encoded([prompt, catalog]).encode()) > self.settings.input_budget:
            raise DomainError("CONTEXT_TOO_LARGE", 409)
        return await self._images(turn, plan, prompt)
