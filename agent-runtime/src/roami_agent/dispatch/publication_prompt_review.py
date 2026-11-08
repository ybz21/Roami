"""Require frozen text in the original Main's actual current model input."""

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.publication_text_evidence import reviewed_text


class PublicationPromptReview:
    def __init__(self, database, artifacts, reviewer):
        self.db, self.artifacts, self.reviewer = database, artifacts, reviewer

    async def inspect(self, binding, required):
        if self.reviewer is None:
            raise DomainError("PUBLICATION_MODEL_CONTEXT_UNAVAILABLE", 409)
        context, _ = await self.reviewer.sources(binding)
        proof = await self.db.call(
            lambda db: reviewed_text(db, binding, required, prompt=context["messages"])
        )
        for item in proof:
            await self.artifacts.verified_path(binding["owner"], item["artifactId"])
        latest, _ = await self.reviewer.sources(binding)
        if latest is not context:
            raise DomainError("PUBLICATION_PROMPT_REVIEW_CHANGED", 409)
        current = await self.db.call(
            lambda db: reviewed_text(db, binding, required, prompt=latest["messages"])
        )
        if current != proof:
            raise DomainError("PUBLICATION_PROMPT_REVIEW_CHANGED", 409)
        return proof
