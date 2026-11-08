"""An independent Main decision requires the frozen content in its real model input."""

from roami_agent.dispatch.publication_image_review import PublicationImageReview
from roami_agent.dispatch.publication_prompt_review import PublicationPromptReview
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.publication_reviews import current_version, save_review


class PublicationReview:
    def __init__(self, database, artifacts, reviewer):
        self.db, self.artifacts, self.reviewer = database, artifacts, reviewer

    async def decide(self, binding, version_id, decision, feedback):
        version, manifest = await self.db.call(lambda db: current_version(db, binding, version_id))
        proof = {}
        if decision == "approved":
            content = manifest["content"]
            if any(name in content for name in ("video", "audio")):
                raise DomainError("PUBLICATION_MEDIA_REVIEW_UNAVAILABLE", 409)
            by_id = {item["id"]: item for item in manifest["artifacts"]}
            text_ids = [
                ident
                for name, value in content.items()
                if name != "images"
                for ident in (value if isinstance(value, list) else [value])
            ]
            text = [by_id[ident] for ident in dict.fromkeys(text_ids)]
            proof["text"] = await PublicationPromptReview(
                self.db, self.artifacts, self.reviewer
            ).inspect(binding, text)
            if content.get("images"):
                proof["images"] = await PublicationImageReview(self.db, self.artifacts).inspect(
                    binding, [by_id[ident] for ident in content["images"]]
                )
            for artifact in manifest["artifacts"]:
                await self.artifacts.verified_path(binding["owner"], artifact["id"])
            # Recheck text after image I/O so interruption or context replacement cannot slip through.
            latest = await PublicationPromptReview(self.db, self.artifacts, self.reviewer).inspect(
                binding, text
            )
            if latest != proof["text"]:
                raise DomainError("PUBLICATION_PROMPT_REVIEW_CHANGED", 409)
        return await self.db.call(
            lambda db: save_review(db, binding, version["id"], decision, feedback, proof),
            write=True,
        )
