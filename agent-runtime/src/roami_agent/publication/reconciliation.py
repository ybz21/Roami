"""Read back an existing post without granting permission to submit another one."""

import hashlib

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.publication.post_journal import PostJournal
from roami_agent.storage.swarm_repository import receipt


class PostReconciliation:
    def __init__(self, database, channel=None, frozen_content=None):
        self.db, self.channel, self.frozen_content = database, channel, frozen_content

    async def confirm(self, owner, project_id, root_id):
        if self.channel is None or self.frozen_content is None:
            raise DomainError("PUBLICATION_RECONCILIATION_UNAVAILABLE", 409)

        def read(db):
            attempt = PostJournal.fact(db, owner, project_id, "publication-attempt:" + root_id)
            if not attempt or attempt.get("kind") != "publication_attempt":
                raise DomainError("PUBLICATION_ATTEMPT_NOT_FOUND", 404)
            context = attempt["context"]
            if context["owner"] != owner or context["projectId"] != project_id:
                raise DomainError("PUBLICATION_PROJECT_SCOPE_CONFLICT", 403)
            submit = PostJournal.fact(
                db, owner, project_id, "publication-post_submit:" + attempt["attemptId"]
            )
            created = PostJournal.fact(
                db, owner, project_id, "publication-post_created:" + attempt["attemptId"]
            )
            if not submit or not created:
                raise DomainError("PUBLICATION_PLATFORM_ID_UNKNOWN", 409)
            return attempt, submit["event"], created["event"]

        attempt, submitted, created = await self.db.call(read)
        context = attempt["context"]
        if context["channel"] != "x":
            raise DomainError("PUBLICATION_CHANNEL_UNAVAILABLE", 409)
        content = await self.frozen_content(context)
        payload = {"text": content["text"]}
        media = submitted["media"]
        if media:
            payload["media"] = {"media_ids": [item["id"] for item in media]}
        if (
            content["versionSha256"] != context["versionSha256"]
            or hashlib.sha256(encoded(payload).encode()).hexdigest() != submitted["requestSha256"]
            or any(created.get(k) != submitted.get(k) for k in submitted if k != "phase")
        ):
            raise DomainError("PUBLICATION_SUBMISSION_SCOPE_CONFLICT", 409)
        channel = await self.channel(context["accountId"])
        public = await channel.confirm(
            context["accountId"], created["platformId"], content["text"], media
        )
        fact = {
            "kind": "publication_public_fact",
            "attemptId": attempt["attemptId"],
            "requestSha256": submitted["requestSha256"],
            **public,
        }

        def save(db):
            if read(db) != (attempt, submitted, created):
                raise DomainError("PUBLICATION_SUBMISSION_SCOPE_CONFLICT", 409)
            return receipt(
                db,
                owner,
                "publication-public:" + attempt["attemptId"],
                fact,
                lambda: fact,
                scope_project_id=project_id,
            )

        return await self.db.call(save, write=True)
