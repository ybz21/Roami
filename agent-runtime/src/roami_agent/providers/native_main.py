"""Per-turn CLI model port; native tools execute only inside the bound provider."""

import asyncio
import hashlib

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.models import ModelEvent
from roami_agent.protocol.serialization import encoded


class NativeMain:
    def __init__(self, binding, turn, command, *, sleep=asyncio.sleep, capabilities=None):
        self.binding, self.turn, self.command, self.sleep = binding, turn, command, sleep
        self.capabilities = capabilities
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
        key = (
            "project-main:"
            + self.turn["id"]
            + ":"
            + hashlib.sha256(payload.encode()).hexdigest()[:24]
        )
        prompt = (
            "You are the existing project's Main, using its bound persistent native CLI. "
            "Preserve the original Main, team, task, memory and publication identities. "
            "Use native tools and the public roami CLI for actual work; host tool definitions are "
            "context, not native callable tools. Do not impersonate a worker or invent run IDs. "
            "Return your actual final human-readable answer; the host delivers it to the same "
            "original Main conversation. Native tool results must not be executed twice. "
            "Unknown publication outcomes stay unknown and must be reconciled before resending.\n"
            + encoded(
                {
                    "projectId": self.binding["project_id"],
                    "mainConversationId": self.binding["conversation_id"],
                    "turnId": self.turn["id"],
                }
            )
            + "\nThe following is the host-prepared conversation context, with its original roles:\n"
            + payload
        )
        if self.capabilities:
            prompt += await self.capabilities.brief(self.binding, self.turn)
        spec = {
            "key": key,
            "executor": self.binding["executor"],
            "sessionId": self.binding["session_id"],
            "preparedFrom": self.binding["launch_key"],
            "persistent": True,
            "prompt": prompt,
        }
        try:
            receipt = await self.command("launch", "--file", "-", spec=spec)
            while True:
                self.verify(receipt)
                result = receipt.get("result")
                if result is not None:
                    if (
                        result.get("inputStopped") is not True
                        or result.get("outcomeKnown") is not True
                    ):
                        raise DomainError("SESSION_STOP_UNCONFIRMED", 409)
                    if result.get("state") != "succeeded":
                        raise DomainError("PROJECT_MAIN_EXECUTION_FAILED", 409)
                    text = result.get("summary")
                    if not isinstance(text, str) or not text.strip():
                        raise DomainError("PROJECT_MAIN_EMPTY_RESULT", 409)
                    yield ModelEvent("text", text)
                    return
                if receipt.get("state") in {"unknown", "failed", "cancelled"}:
                    raise DomainError("SESSION_STOP_UNCONFIRMED", 409)
                await self.sleep(1)
                receipt = await self.command("status", "--key", key)
        except asyncio.CancelledError:
            # Cancellation of the host await alone does not stop a native provider.
            receipt = await asyncio.shield(self.command("cancel", "--key", key))
            self.verify(receipt)
            result = receipt.get("result") or {}
            if result.get("inputStopped") is not True or result.get("outcomeKnown") is not True:
                raise DomainError("SESSION_STOP_UNCONFIRMED", 409) from None
            raise
