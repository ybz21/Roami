"""Verify frozen text bytes around current independent-Main read evidence."""

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.publication_text_evidence import reviewed_text


class PublicationTextReview:
    def __init__(self, database, artifacts):
        self.db, self.artifacts = database, artifacts

    async def inspect(self, binding, required):
        proof = await self.db.call(lambda db: reviewed_text(db, binding, required))
        for item in proof:
            await self.artifacts.verified_path(binding["owner"], item["artifactId"])
        current = await self.db.call(lambda db: reviewed_text(db, binding, required))
        if current != proof:
            raise DomainError("PUBLICATION_TEXT_REVIEW_CHANGED", 409)
        return proof
