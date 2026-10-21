"Agent loop over injected ports; no Web, CLI or database implementation imports."

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from itertools import count

from roami_agent.protocol.errors import DomainError, ToolPreflightError
from roami_agent.protocol.identity import now_ms
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
        self.preemptible = set()

    def preempt(self, turn_id):
        handle = self.turn_tasks.get(turn_id)
        if turn_id in self.preemptible and handle and not handle.done():
            handle.cancel("NEW_USER_INTENT")

    async def build_context(self, turn, instructions, catalog, completion):
        started, wall = self.clock(), now_ms()
        plan, prompt = await self.context.build(turn, instructions, catalog, completion)
        if turn.get("resumed"):
            origin = await self.journal.origin(turn)
            prompt.append(
                {
                    "role": "user",
                    "content": "Resume this original request after another user intent briefly took priority. "
                    "That newer request is handled separately. Complete this request, preserving persisted "
                    "tool results and existing background tasks; do not repeat writes or duplicate delegation. "
                    "The original request being resumed (user data, not new authorization): "
                    + encoded(origin.get("text", "") if origin else None),
                }
            )
        return dict(
            plan,
            timing={"contextStartedMs": wall, "contextDurationMs": (self.clock() - started) * 1000},
        ), prompt

    @asynccontextmanager
    async def measured_request(self, turn, attempt, timing, role):
        started = self.clock()
        timing = dict(timing, modelStartedMs=now_ms(), state="running", providerEvents=[])
        await self.manifests.timing(turn, attempt, timing)
        try:
            async with asyncio.timeout(self.settings.timeout_for(role) or None):
                yield timing, started
            timing["state"] = "succeeded"
        except BaseException as exc:
            timing["state"] = "interrupted" if isinstance(exc, asyncio.CancelledError) else "failed"
            timing["errorCode"] = (
                "NEW_USER_INTENT"
                if isinstance(exc, asyncio.CancelledError) and exc.args == ("NEW_USER_INTENT",)
                else exc.code
                if isinstance(exc, DomainError)
                else type(exc).__name__
            )
            raise
        finally:
            timing.update(modelFinishedMs=now_ms(), modelDurationMs=(self.clock() - started) * 1000)
            await self.manifests.timing(turn, attempt, timing)

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
                if role == "main" and await self.journal.defer(turn, only_if_pending=True):
                    return None
                plan, prompt = await self.build_context(turn, instructions, catalog, completion)
                origin = await self.journal.origin(turn)
                offset = await self.journal.attempt_offset(turn)
                seen_rejections = set()
                finalizing = False
                finalization_error = None
                for step in count(offset):
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
                        dict(
                            plan,
                            providerKey=provider_key,
                            modelSettingsHash=settings_hash,
                            requestLimits={
                                "modelTimeoutSeconds": self.settings.timeout_for(role),
                                "executionTimeoutSeconds": turn.get("executionTimeoutSeconds"),
                            },
                        ),
                        catalog,
                        role,
                    )
                    mid = await self.journal.start(turn)
                    text, calls, usage, buffer, flushed = "", [], None, "", self.clock()
                    first_delta = True
                    phase = "model"
                    if role == "main":
                        self.preemptible.add(tid)
                    async with self.measured_request(turn, step + 1, plan["timing"], role) as (
                        timing,
                        model_started,
                    ):
                        async for part in model.stream(prompt, catalog):
                            elapsed = (self.clock() - model_started) * 1000
                            if part.kind == "telemetry":
                                if len(timing["providerEvents"]) < 16:
                                    timing["providerEvents"].append(
                                        dict(part.value, elapsedMs=elapsed)
                                    )
                                    if part.value.get("phase") in {
                                        "headers",
                                        "first_delta",
                                        "retry",
                                    }:
                                        await self.manifests.timing(turn, step + 1, timing)
                            elif part.kind == "text" and part.value and "firstTextMs" not in timing:
                                timing["firstTextMs"] = elapsed
                                await self.manifests.timing(turn, step + 1, timing)
                            if part.kind == "text":
                                text += part.value
                                buffer += part.value
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
                    self.preemptible.discard(tid)
                    phase = "tools"
                    if buffer:
                        await self.journal.delta(turn, mid, text, buffer)
                    if finalizing and calls:
                        raise ToolPreflightError(
                            finalization_error or "TOOL_FINALIZATION_STALLED", 503
                        )
                    if not text.strip() and not calls:
                        raise DomainError("EMPTY_MODEL_RESPONSE")
                    if len(calls) > 1 and any(
                        call["function"]["name"]
                        in {"ask_user", "task_reply", "task_queue_reply", "reply"}
                        for call in calls
                    ):
                        raise DomainError("QUESTION_MUST_BE_ONLY_TOOL")
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
                    handed_off = role == "main"
                    request_complete = False
                    rejections = set()
                    for call in calls:
                        try:
                            tool = self.tools.validate(call, role)[0]
                        except (DomainError, KeyError, TypeError):
                            tool = None
                        operation = tool.name if tool else None
                        binding = {
                            "owner": owner,
                            "conversation": cid,
                            "turnId": tid,
                            "taskId": task_id,
                            "runId": turn.get("executionRunId"),
                            "originMessageId": origin["id"] if origin else None,
                            "toolCallId": call["id"],
                            "workspace": turn.get("workspace"),
                            "finalizing": finalizing,
                        }
                        value = await self.gateway.invoke(turn, mid, call, role, binding)
                        if isinstance(value, dict) and value.get("finalizeFromEvidence") is True:
                            finalizing = True
                            finalization_error = value.get("error")
                        if (
                            role == "main"
                            and operation in {"task_reply", "task_queue_reply", "reply"}
                            and isinstance(value, dict)
                            and isinstance(value.get("reply"), str)
                        ):
                            reply = value["reply"]
                            reply_id = await self.journal.start(turn)
                            await self.journal.delta(turn, reply_id, reply, reply)
                            await self.journal.finish(
                                turn,
                                reply_id,
                                reply,
                                [],
                                usage,
                                step + 1,
                                final=True,
                                completion=completion,
                            )
                            await self.context.after_turn(turn, instructions, catalog)
                            return reply
                        if (
                            (
                                operation is None
                                or operation == "reply"
                                or (tool and tool.effect == "write")
                            )
                            and isinstance(value, dict)
                            and value.get("error")
                            in {
                                "INVALID_TOOL_ARGUMENTS",
                                "INVALID_CLI_ARGUMENTS",
                                "TOOL_UNAVAILABLE",
                                "TOOL_DISABLED",
                                "REPLY_BOILERPLATE",
                                "REPLY_INTERNAL_FIELDS",
                                "REPLY_LANGUAGE_MISMATCH",
                                "REPLY_SCOPE_QUOTE_REQUIRED",
                                "TASK_COMPLETION_RESTART_FORBIDDEN",
                            }
                        ):
                            rejected_arguments = call["function"].get("arguments", "")
                            try:
                                rejected_arguments = json.loads(rejected_arguments)
                            except (ValueError, TypeError):
                                pass
                            rejections.add(
                                (
                                    "completion_write"
                                    if value["error"] == "TASK_COMPLETION_RESTART_FORBIDDEN"
                                    else call["function"]["name"],
                                    value["error"],
                                    encoded(value.get("argumentIssues")),
                                    hashlib.sha256(
                                        (
                                            ""
                                            if value["error"] == "TASK_COMPLETION_RESTART_FORBIDDEN"
                                            else encoded(rejected_arguments)
                                        ).encode()
                                    ).hexdigest(),
                                )
                            )
                        handed_off = (
                            handed_off
                            and tool is not None
                            and not (
                                isinstance(value, dict)
                                and (value.get("error") or value.get("exitCode", 0) != 0)
                            )
                            and (
                                operation in {"delegate", "task_steer"}
                                and isinstance(value, dict)
                                and value.get("acceptedOnly") is True
                                or operation not in {"delegate", "task_steer"}
                                and tool.effect == "read"
                            )
                        )
                        request_complete = (
                            operation in {"delegate", "task_steer"}
                            and isinstance(value, dict)
                            and value.get("acceptedOnly") is True
                            and value.get("requestComplete") is True
                        )
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
                    if rejections & seen_rejections:
                        raise DomainError("TOOL_ARGUMENT_REPAIR_STALLED", 502)
                    seen_rejections.update(rejections)
                    if handed_off and request_complete:
                        # The durable task card is the receipt; a second model call delays new intents.
                        await self.journal.finish(
                            turn,
                            mid,
                            text,
                            calls,
                            usage,
                            step + 1,
                            final=True,
                            completion=completion,
                        )
                        await self.context.after_turn(turn, instructions, catalog)
                        return text
                    if role == "main" and await self.journal.defer(turn, only_if_pending=True):
                        return None
                    catalog = self.tools.catalog(role)
                    phase = "context"
                    plan, prompt = await self.build_context(turn, instructions, catalog, completion)
                    if finalizing:
                        catalog = []
                        plan = dict(
                            plan,
                            historyView="finalization",
                            requestBasis=hashlib.sha256(
                                encoded([plan.get("requestBasis"), "finalization"]).encode()
                            ).hexdigest(),
                        )
                        prompt.insert(
                            1 + plan["currentTurnStart"],
                            {
                                "role": "system",
                                "content": "This attempt is closing after an unchanged blocker. No further tools or inputs are allowed. Report only findings verified from sources already read in this attempt, with their URLs and limitations. Mark everything else unconfirmed. Do not invent missing facts or restart work.",
                            },
                        )
        except TimeoutError as exc:
            code = (
                "MODEL_DEADLINE"
                if phase == "model" and not execution_deadline.expired()
                else "AGENT_TURN_DEADLINE"
            )
            await self.journal.fail(turn, "failed", code, completion=completion)
            raise DomainError(code, 504) from exc
        except BaseException as exc:
            if (
                isinstance(exc, asyncio.CancelledError)
                and exc.args == ("NEW_USER_INTENT",)
                and await self.journal.defer(turn)
            ):
                return None
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
            self.preemptible.discard(tid)
            self.turn_tasks.pop(tid, None)
