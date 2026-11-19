"""Verify frozen text bytes around current independent-Main read evidence."""

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.publication_text_evidence import reviewed_text


class PublicationTextReview:
    def __init__(self, database, artifacts):
        self.db, self.artifacts = database, artifacts

    async def inspect(self, binding, required, *, native_input=None):
        def inspect_input(db):
            return reviewed_text(db, binding, required, native_input=native_input)

        proof = await self.db.call(inspect_input)
        for item in proof:
            await self.artifacts.verified_path(binding["owner"], item["artifactId"])
        current = await self.db.call(inspect_input)
        if current != proof:
            raise DomainError("PUBLICATION_TEXT_REVIEW_CHANGED", 409)
        return proof
