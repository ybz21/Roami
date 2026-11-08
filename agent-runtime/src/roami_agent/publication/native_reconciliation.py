"""Join native submit intent, frozen content and a host public readback."""

import hashlib

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.publication.post_journal import PostJournal
from roami_agent.storage.swarm_repository import receipt


class NativeReconciliation:
    def __init__(self, database, frozen_content, public_readback):
        self.db = database
        self.frozen_content, self.public_readback = frozen_content, public_readback

    async def confirm(self, owner, project_id, root_id):
        def read(db):
            attempt = PostJournal.fact(db, owner, project_id, "publication-attempt:" + root_id)
            if not attempt or attempt.get("kind") != "publication_attempt":
                raise DomainError("PUBLICATION_ATTEMPT_NOT_FOUND", 404)
            context = attempt["context"]
            if context["owner"] != owner or context["projectId"] != project_id:
                raise DomainError("PUBLICATION_PROJECT_SCOPE_CONFLICT", 403)
            facts = [
                PostJournal.fact(db, owner, project_id, prefix + attempt["attemptId"])
                for prefix in (
                    "publication-post_submit:",
                    "publication-post_created:",
                    "publication-public:",
                )
            ]
            if not all(facts[:2]):
                raise DomainError("PUBLICATION_PLATFORM_ID_UNKNOWN", 409)
            return attempt, *facts

        attempt, submitted, created, previous = await self.db.call(read)
        if previous:
            return previous
        context = attempt["context"]
        submit, candidate = submitted["event"], created["event"]
        prepared = submit.get("prepared")
        frozen = await self.frozen_content(context)
        if (
            not isinstance(prepared, dict)
            or hashlib.sha256(encoded(prepared).encode()).hexdigest() != submit["requestSha256"]
            or frozen.get("versionSha256") != context["versionSha256"]
            or not isinstance(frozen.get("content"), dict)
            or prepared.get("content") != frozen["content"]
            or not isinstance(frozen.get("media"), list)
            or prepared.get("media") != frozen["media"]
            or any(candidate.get(key) != value for key, value in submit.items() if key != "phase")
        ):
            raise DomainError("PUBLICATION_SUBMISSION_SCOPE_CONFLICT", 409)
        public = await self.public_readback(context, prepared, candidate.get("platformId"))
        if not isinstance(public, dict) or any(
            public.get(key) != value
            for key, value in {
                "state": "public",
                "accountId": context["accountId"],
                "channel": context["channel"],
                "platformId": candidate.get("platformId"),
            }.items()
        ):
            raise DomainError("PUBLICATION_RECEIPT_SCOPE_CONFLICT", 403)
        fact = {
            **public,
            "kind": "publication_public_fact",
            "attemptId": attempt["attemptId"],
            "requestSha256": submit["requestSha256"],
        }

        def save(db):
            current = read(db)
            if current[:3] != (attempt, submitted, created):
                raise DomainError("PUBLICATION_SUBMISSION_SCOPE_CONFLICT", 409)
            if current[3]:
                return current[3]
            return receipt(
                db,
                owner,
                "publication-public:" + attempt["attemptId"],
                fact,
                lambda: fact,
                scope_project_id=project_id,
            )

        return await self.db.call(save, write=True)
