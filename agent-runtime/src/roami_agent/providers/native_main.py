"""Per-turn CLI model port; native tools execute only inside the bound provider."""

import asyncio
import hashlib
import re

from roami_agent.context.native_prompt import INLINE_LIMIT, NativePrompt
from roami_agent.protocol.errors import DomainError, NativeRouteUnavailable
from roami_agent.protocol.models import ModelEvent
from roami_agent.protocol.serialization import encoded


class NativeMain:
    def __init__(
        self, binding, turn, command, *, sleep=asyncio.sleep, capabilities=None, delivery=None
    ):
        self.binding, self.turn, self.command, self.sleep = binding, turn, command, sleep
        self.capabilities = capabilities
        self.delivery = delivery
        self.stream_count = 0
        self.model = binding["model"]
        self.provider_key = "native-cli:" + binding["executor"] + ":" + binding["provider_id"]
        self.settings_hash = hashlib.sha256(encoded(binding).encode()).hexdigest()

    def with_model(self, model, *, free_only=False):
        if model not in {None, "auto", self.model, "roami-claude/" + self.model}:
            raise DomainError("PROJECT_MAIN_MODEL_CONFLICT", 409)
        if free_only and self.model != "free":
            raise DomainError("PROJECT_MAIN_MODEL_CONFLICT", 409)
        return self

    def verify(self, receipt):
        binding = receipt.get("sessionBinding") or {}
        original = self.binding["binding"]
        fields = (
            "id",
            "name",
            "tmuxId",
            "created",
            "server",
            "pane",
            "pid",
            "directory",
            "providerConversationId",
            "hostProof",
            "directoryProof",
            "providerHome",
            "providerHomeProof",
        )
        if receipt.get("session") != self.binding["session_id"] or any(
            binding.get(key) != original.get(key) for key in fields
        ):
            raise DomainError("SESSION_PROVIDER_BINDING_CHANGED", 409)

    async def stream(self, messages, tools):
        if (
            self.turn["conversation_id"] != self.binding["conversation_id"]
            or self.turn["owner_id"] != self.binding["owner_id"]
        ):
            raise DomainError("PROJECT_MAIN_IDENTITY_MISMATCH", 409)
        payload = encoded(messages)
        payload_bytes = payload.encode()
        self.stream_count += 1
        key = (
            "project-main:" + self.turn["id"] + ":" + hashlib.sha256(payload_bytes).hexdigest()[:24]
        )
        retry = self.turn.get("native_route_retry", 0)
        if retry:
            key += ":retry-" + str(retry)
        prompt = (
            "You are the existing project's Main, using its bound persistent native CLI. "
            "Preserve the original Main, team, tasks, memory and recorded external action identities. "
            "Use native tools and the public roami CLI for actual work; host tool definitions are "
            "context, not native callable tools. Do not impersonate a worker or invent run IDs. "
            "Return your actual final human-readable answer; the host delivers it to the same "
            "original Main conversation. Native tool results must not be executed twice. "
            "Reconcile unknown external outcomes by their original identity before resending.\n"
            + encoded(
                {
                    "projectId": self.binding["project_id"],
                    "mainConversationId": self.binding["conversation_id"],
                    "turnId": self.turn["id"],
                }
            )
        )
        prepared = None
        launch_turn = {**self.turn, "native_launch_key": key}
        if (
            self.capabilities
            and self.binding["executor"] == "claude"
            and self.turn.get("trigger_kind") == "continuation"
            and len(payload_bytes) > INLINE_LIMIT
        ):
            packet = NativePrompt(messages)
            if packet.batch_index is not None:
                prepared = packet
        if prepared is None:
            prompt += (
                "\nThe following is the host-prepared conversation context, with its original roles:\n"
                + payload
            )
        if self.capabilities:
            if prepared is not None:
                prompt += await self.capabilities.brief(
                    self.binding, launch_turn, prepared_context=prepared
                )
            else:
                schemas = [
                    tool for tool in tools or [] if tool.get("function", {}).get("name") != "reply"
                ]
                prompt += (
                    "\nHost capability schemas for this turn follow. These are not native tools: "
                    "invoke their exact names and arguments through the signed capability call below. "
                    "Core read supports retained artifact:// paths; do not recover syntax or signed "
                    "contexts from old transcripts.\n"
                    + encoded(schemas)
                    + "\nEnd host capability schemas.\n"
                )
                prompt += await self.capabilities.brief(self.binding, launch_turn)
        spec = {
            "key": key,
            "executor": self.binding["executor"],
            "sessionId": self.binding["session_id"],
            "preparedFrom": self.binding["launch_key"],
            "persistent": True,
            "prompt": prompt,
        }
        may_have_submitted = False
        try:
            admission_waits = 0
            while True:
                may_have_submitted = True
                try:
                    receipt = await self.command("launch", "--file", "-", spec=spec)
                    break
                except DomainError as error:
                    if error.code != "SESSION_NOT_IDLE":
                        raise
                    # Go rejects this before writing the launch spec or submitting input.
                    may_have_submitted = False
                    admission_waits += 1
                    await self.sleep(min(admission_waits, 10))
            unknown_polls = 0
            delivery_pending = False
            while True:
                self.verify(receipt)
                result = receipt.get("result")
                if self.delivery:
                    if (
                        not delivery_pending
                        and receipt.get("state") == "unknown"
                        and receipt.get("observationErrorCode") == "SESSION_SUBMISSION_UNCONFIRMED"
                    ):
                        await self.delivery(key, "awaiting_native")
                        delivery_pending = True
                    elif delivery_pending and (
                        result is not None or receipt.get("state") in {"running", "cancelling"}
                    ):
                        await self.delivery(key, "closed")
                        delivery_pending = False
                if result is not None:
                    if (
                        result.get("inputStopped") is not True
                        or result.get("outcomeKnown") is not True
                    ):
                        raise DomainError("SESSION_STOP_UNCONFIRMED", 409)
                    if result.get("state") != "succeeded":
                        # The CLI only emits this compaction code for proven route exhaustion.
                        if (
                            self.binding["executor"] == "claude"
                            and self.stream_count == 1
                            and result.get("state") == "failed"
                            and result.get("errorCode")
                            in ("MODEL_ROUTE_NO_AVAILABLE_MEMBER", "CLAUDE_COMPACTION_FAILED")
                            and isinstance(result.get("stopEvidenceSha256"), str)
                            and re.fullmatch(r"[a-f0-9]{64}", result["stopEvidenceSha256"])
                        ):
                            raise NativeRouteUnavailable(
                                result["errorCode"], result["stopEvidenceSha256"]
                            )
                        raise DomainError("PROJECT_MAIN_EXECUTION_FAILED", 409)
                    text = result.get("summary")
                    if not isinstance(text, str) or not text.strip():
                        raise DomainError("PROJECT_MAIN_EMPTY_RESULT", 409)
                    yield ModelEvent("text", text)
                    return
                if receipt.get("state") in {"failed", "cancelled"}:
                    raise DomainError("SESSION_STOP_UNCONFIRMED", 409)
                unknown_polls = unknown_polls + 1 if receipt.get("state") == "unknown" else 0
                await self.sleep(min(1 + unknown_polls, 10))
                try:
                    # Startup hooks and terminal proofs can arrive after the launch receipt.
                    sub = (
                        "reconcile-session"
                        if unknown_polls and unknown_polls % 10 == 0
                        else "status"
                    )
                    receipt = await self.command(sub, "--key", key)
                except DomainError as error:
                    if error.code != "CODING_EXECUTOR_UNAVAILABLE":
                        raise
                except (TimeoutError, OSError):
                    pass
        except asyncio.CancelledError:
            if not may_have_submitted:
                raise
            # Cancellation of the host await alone does not stop a native provider.
            receipt = await asyncio.shield(self.command("cancel", "--key", key))
            self.verify(receipt)
            result = receipt.get("result") or {}
            if result.get("inputStopped") is not True or result.get("outcomeKnown") is not True:
                raise DomainError("SESSION_STOP_UNCONFIRMED", 409) from None
            raise
        finally:
            if prepared is not None:
                self.capabilities.release_prompt(launch_turn)
