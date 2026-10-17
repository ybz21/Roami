"Agent loop over injected ports; no Web, CLI or database implementation imports."

import asyncio
import hashlib

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import Model
from roami_agent.protocol.ports import (
    ContextBuilder,
    LoopSettings,
    ManifestWriter,
    ToolCatalog,
    ToolInvoker,
    TurnWriter,
)
from roami_agent.protocol.serialization import encoded


class AgentLoop:
    def __init__(
        self,
        model: Model,
        worker_model: Model,
        settings: LoopSettings,
        context: ContextBuilder,
        journal: TurnWriter,
        tools: ToolCatalog,
        manifests: ManifestWriter,
        charge_task,
        turn_tasks,
        clock,
        gateway: ToolInvoker,
    ):
        self.model, self.worker_model, self.settings = model, worker_model, settings
        self.context, self.journal, self.tools = context, journal, tools
        self.manifests, self.charge_task, self.turn_tasks = manifests, charge_task, turn_tasks
        self.clock = clock
        self.gateway = gateway

    async def run(self, turn, role, *, task_id=None, completion=None):
        tid, cid, owner = (turn[k] for k in ["id", "conversation_id", "owner_id"])
        self.turn_tasks[tid] = asyncio.current_task()
        model = self.model if role == "main" else self.worker_model
        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                instructions = (
                    self.settings.main_instructions
                    if role == "main"
                    else self.settings.worker_instructions
                )
                catalog = self.tools.catalog(role)
                plan, prompt = await self.context.build(turn, instructions, catalog, completion)
                origin = await self.journal.origin(turn)
                for step in range(self.settings.max_steps):
                    if task_id:
                        await self.charge_task(task_id)
                    wire_hash = hashlib.sha256(encoded([prompt, catalog]).encode()).hexdigest()
                    await self.manifests.record(
                        turn, step + 1, model.model, wire_hash, plan, catalog, role
                    )
                    mid = await self.journal.start(turn)
                    text, calls, usage, buffer, flushed = "", [], None, "", self.clock()
                    async for part in model.stream(prompt, catalog):
                        if part.kind == "text":
                            text += part.value
                            buffer += part.value
                            if len(text) > 100_000:
                                raise DomainError("MODEL_OUTPUT_LIMIT")
                            if len(buffer.encode()) >= 1024 or self.clock() - flushed >= 0.1:
                                await self.journal.delta(turn, mid, text, buffer)
                                buffer, flushed = "", self.clock()
                        elif part.kind == "tool":
                            calls.append(part.value)
                        elif part.kind == "usage":
                            usage = part.value
                    if buffer:
                        await self.journal.delta(turn, mid, text, buffer)
                    if not text.strip() and not calls:
                        raise DomainError("EMPTY_MODEL_RESPONSE")
                    if len(calls) > 16:
                        raise DomainError("TOOL_CALL_LIMIT")
                    await self.journal.finish(
                        turn,
                        mid,
                        text,
                        calls,
                        usage,
                        step + 1,
                        final=not calls,
                        completion=completion,
                    )
                    prompt.append(
                        {
                            "role": "assistant",
                            "content": text,
                            **({"tool_calls": calls} if calls else {}),
                        }
                    )
                    if not calls:
                        return text
                    for call in calls:
                        binding = {
                            "owner": owner,
                            "conversation": cid,
                            "turnId": tid,
                            "taskId": task_id,
                            "originMessageId": origin["id"] if origin else None,
                            "toolCallId": call["id"],
                            "workspace": turn.get("workspace"),
                        }
                        value = await self.gateway.invoke(turn, mid, call, role, binding)
                        prompt.append(
                            {"role": "tool", "tool_call_id": call["id"], "content": encoded(value)}
                        )
                    catalog = self.tools.catalog(role)
                    plan, prompt = await self.context.build(turn, instructions, catalog, completion)
                raise DomainError("AGENT_STEP_LIMIT")
        except BaseException as exc:
            state = "interrupted" if isinstance(exc, asyncio.CancelledError) else "failed"
            code = (
                exc.code
                if isinstance(exc, DomainError)
                else "TURN_INTERRUPTED"
                if state == "interrupted"
                else "MODEL_ERROR"
            )
            await self.journal.fail(turn, state, code)
            raise
        finally:
            self.turn_tasks.pop(tid, None)
