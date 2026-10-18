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
        phase = "context"
        try:
            execution_deadline = asyncio.timeout(turn.get("executionTimeoutSeconds"))
            async with execution_deadline:
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
                    provider_key = getattr(model, "provider_key", "unidentified")
                    settings_hash = getattr(model, "settings_hash", None)
                    wire_hash = hashlib.sha256(
                        encoded(
                            [provider_key, model.model, "chat-v1", settings_hash, prompt, catalog]
                        ).encode()
                    ).hexdigest()
                    await self.manifests.record(
                        turn,
                        step + 1,
                        model.model,
                        wire_hash,
                        dict(plan, providerKey=provider_key, modelSettingsHash=settings_hash),
                        catalog,
                        role,
                    )
                    mid = await self.journal.start(turn)
                    text, calls, usage, buffer, flushed = "", [], None, "", self.clock()
                    first_delta = True
                    phase = "model"
                    async with asyncio.timeout(self.settings.timeout_for(role)):
                        async for part in model.stream(prompt, catalog):
                            if part.kind == "text":
                                text += part.value
                                buffer += part.value
                                if len(text) > 100_000:
                                    raise DomainError("MODEL_OUTPUT_LIMIT")
                                if (
                                    first_delta
                                    or len(buffer.encode()) >= 1024
                                    or self.clock() - flushed >= 0.1
                                ):
                                    await self.journal.delta(turn, mid, text, buffer)
                                    buffer, flushed = "", self.clock()
                                    first_delta = False
                            elif part.kind == "tool":
                                calls.append(part.value)
                            elif part.kind == "usage":
                                usage = part.value
                    phase = "tools"
                    if buffer:
                        await self.journal.delta(turn, mid, text, buffer)
                    if not text.strip() and not calls:
                        raise DomainError("EMPTY_MODEL_RESPONSE")
                    if len(calls) > 1 and any(
                        call["function"]["name"] == "ask_user" for call in calls
                    ):
                        raise DomainError("QUESTION_MUST_BE_ONLY_TOOL")
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
                        await self.context.after_turn(turn, instructions, catalog)
                        return text
                    for call in calls:
                        binding = {
                            "owner": owner,
                            "conversation": cid,
                            "turnId": tid,
                            "taskId": task_id,
                            "runId": turn.get("executionRunId"),
                            "originMessageId": origin["id"] if origin else None,
                            "toolCallId": call["id"],
                            "workspace": turn.get("workspace"),
                        }
                        value = await self.gateway.invoke(turn, mid, call, role, binding)
                        if (
                            call["function"]["name"] == "ask_user"
                            and isinstance(value, dict)
                            and value.get("question")
                        ):
                            await self.journal.finish(
                                turn,
                                mid,
                                text,
                                calls,
                                usage,
                                step + 1,
                                final=True,
                                completion=completion,
                                question=value["question"],
                            )
                            await self.context.after_turn(turn, instructions, catalog)
                            return text
                        prompt.append(
                            {"role": "tool", "tool_call_id": call["id"], "content": encoded(value)}
                        )
                    catalog = self.tools.catalog(role)
                    phase = "context"
                    plan, prompt = await self.context.build(turn, instructions, catalog, completion)
                raise DomainError("AGENT_STEP_LIMIT")
        except TimeoutError as exc:
            code = (
                "MODEL_DEADLINE"
                if phase == "model" and not execution_deadline.expired()
                else "AGENT_TURN_DEADLINE"
            )
            await self.journal.fail(turn, "failed", code, completion=completion)
            raise DomainError(code, 504) from exc
        except BaseException as exc:
            interrupted = isinstance(exc, asyncio.CancelledError) or (
                isinstance(exc, DomainError) and exc.code == "TURN_INTERRUPTED"
            )
            state = "interrupted" if interrupted else "failed"
            code = (
                exc.code
                if isinstance(exc, DomainError)
                else "TURN_INTERRUPTED"
                if state == "interrupted"
                else "MODEL_ERROR"
            )
            await self.journal.fail(turn, state, code, completion=completion)
            raise
        finally:
            self.turn_tasks.pop(tid, None)
