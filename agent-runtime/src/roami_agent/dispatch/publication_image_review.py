"""Verify immutable image bytes around the Main input-evidence lookup."""

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.publication_image_evidence import reviewed_images


class PublicationImageReview:
    def __init__(self, database, artifacts):
        self.db, self.artifacts = database, artifacts

    async def inspect(self, binding, required):
        proof = await self.db.call(lambda db: reviewed_images(db, binding, required))
        references = dict.fromkeys(
            reference
            for item in proof
            for reference in (item["artifactId"], item["imageReadArtifactId"])
        )
        for reference in references:
            await self.artifacts.verified_path(binding["owner"], reference)
        current = await self.db.call(lambda db: reviewed_images(db, binding, required))
        if current != proof:
            raise DomainError("PUBLICATION_IMAGE_REVIEW_CHANGED", 409)
        return proof
