"""Persist final-submit intent before a host-owned Chrome or ADB action."""

import hashlib

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded


class NativeSubmission:
    def __init__(self, journal, adapter):
        self.journal, self.adapter = journal, adapter

    async def submit(self, binding, release_id):
        attempt = await self.journal.reserve(binding, release_id)
        context = attempt["context"]
        # The adapter reads frozen bytes and the live native scene itself.
        prepared = await self.adapter.prepare(context)
        if (
            not isinstance(prepared, dict)
            or prepared.get("versionSha256") != context["versionSha256"]
            or prepared.get("accountId") != context["accountId"]
            or prepared.get("channel") != context["channel"]
            or prepared.get("resourceId") != context["resourceId"]
            or not isinstance(prepared.get("media"), list)
            or not isinstance(prepared.get("content"), dict)
        ):
            raise DomainError("PUBLICATION_NATIVE_PREPARATION_CONFLICT", 409)
        common = {key: context[key] for key in ("businessKey", "accountId", "versionSha256")}
        common.update(
            requestSha256=hashlib.sha256(encoded(prepared).encode()).hexdigest(),
            media=prepared["media"],
            prepared=prepared,
        )
        await self.journal.record(binding, attempt, {**common, "phase": "post_submit"})
        # Failure after this point remains unknown; a retry must only reconcile.
        result = await self.adapter.submit_once(context, prepared)
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("platformId"), str)
            or not result["platformId"]
        ):
            raise DomainError("PUBLICATION_PLATFORM_ID_UNKNOWN", 409)
        return await self.journal.record(
            binding,
            attempt,
            {**common, "phase": "post_created", "platformId": result["platformId"]},
        )
