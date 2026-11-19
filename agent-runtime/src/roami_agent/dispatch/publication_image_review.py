"""Verify immutable image bytes around the Main input-evidence lookup."""

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.publication_image_evidence import reviewed_images


class PublicationImageReview:
    def __init__(self, database, artifacts):
        self.db, self.artifacts = database, artifacts

    async def inspect(self, binding, required, *, native_input=None):
        def inspect_input(db):
            return reviewed_images(db, binding, required, native_input=native_input)

        proof = await self.db.call(inspect_input)
        references = dict.fromkeys(
            reference
            for item in proof
            for reference in (
                item["artifactId"],
                item.get("imageReadArtifactId", item["artifactId"]),
            )
        )
        for reference in references:
            await self.artifacts.verified_path(binding["owner"], reference)
        current = await self.db.call(inspect_input)
        if current != proof:
            raise DomainError("PUBLICATION_IMAGE_REVIEW_CHANGED", 409)
        return proof
