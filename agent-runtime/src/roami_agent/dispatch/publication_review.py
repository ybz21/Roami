"""An independent Main decision requires the frozen content in its real model input."""

from roami_agent.dispatch.publication_image_review import PublicationImageReview
from roami_agent.dispatch.publication_media_review import PublicationMediaReview
from roami_agent.dispatch.publication_prompt_review import PublicationPromptReview
from roami_agent.protocol.errors import DomainError
from roami_agent.storage.publication_reviews import current_version, save_review, version_text


class PublicationReview:
    def __init__(self, database, artifacts, reviewer, *, native_review_input=None):
        self.db, self.artifacts, self.reviewer = database, artifacts, reviewer
        self.native_review_input = native_review_input

    async def decide(self, binding, version_id, decision, feedback):
        version, manifest = await self.db.call(lambda db: current_version(db, binding, version_id))
        proof = {}
        native_input = None
        if decision == "approved":
            if binding.get("nativeCapabilityCall"):
                if self.native_review_input is None:
                    raise DomainError("PUBLICATION_MODEL_CONTEXT_UNAVAILABLE", 409)
                native_input = await self.native_input(binding)
                proof["nativeInput"] = {
                    key: native_input[key] for key in ("providerId", "promptId", "requestSha256")
                }
            content = manifest["content"]
            by_id = {item["id"]: item for item in manifest["artifacts"]}
            text = version_text(manifest)
            proof["text"] = await PublicationPromptReview(
                self.db, self.artifacts, self.reviewer
            ).inspect(binding, text, native_input=native_input)
            if content.get("images"):
                proof["images"] = await PublicationImageReview(self.db, self.artifacts).inspect(
                    binding,
                    [by_id[ident] for ident in content["images"]],
                    native_input=native_input,
                )
            media = [by_id[content[name]] for name in ("video", "audio") if name in content]
            if media:
                proof["media"] = await PublicationMediaReview(
                    self.db, self.artifacts, self.reviewer
                ).inspect(binding, version_id, media, native_input=native_input)
            for artifact in manifest["artifacts"]:
                await self.artifacts.verified_path(binding["owner"], artifact["id"])
            if native_input is not None and await self.native_input(binding) != native_input:
                raise DomainError("PUBLICATION_PROMPT_REVIEW_CHANGED", 409)
            # Recheck text after image I/O so interruption or context replacement cannot slip through.
            latest = await PublicationPromptReview(self.db, self.artifacts, self.reviewer).inspect(
                binding, text, native_input=native_input
            )
            if latest != proof["text"]:
                raise DomainError("PUBLICATION_PROMPT_REVIEW_CHANGED", 409)
        native_options = {"native_input": native_input} if native_input is not None else {}
        return await self.db.call(
            lambda db: save_review(
                db, binding, version["id"], decision, feedback, proof, **native_options
            ),
            write=True,
        )

    async def native_input(self, binding):
        try:
            return await self.native_review_input(binding)
        except DomainError as error:
            if error.code != "NATIVE_CAPABILITY_INPUT_UNCONFIRMED":
                raise
            raise DomainError("PUBLICATION_MODEL_CONTEXT_UNAVAILABLE", 409) from error
