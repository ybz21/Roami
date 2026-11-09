"""Review sampled pixels and complete final-track text from the same frozen media."""

import json

from roami_agent.dispatch.publication_prompt_review import PublicationPromptReview
from roami_agent.protocol.errors import DomainError
from roami_agent.publication.media_transcription import transcript_receipt
from roami_agent.storage.publication_media_evidence import media_snapshot, reviewed_media_images


class PublicationMediaReview:
    def __init__(self, database, artifacts, reviewer):
        self.db, self.artifacts, self.reviewer = database, artifacts, reviewer

    async def inspect(self, binding, version_id, required):
        snapshots = await self.db.call(lambda db: media_snapshot(db, binding, version_id, required))
        text = []
        for snapshot in snapshots:
            _, raw = await self.artifacts.read(binding["owner"], snapshot["report"]["id"])
            try:
                report = json.loads(raw)
                if (
                    report["sourceSha256"] != snapshot["sourceSha256"]
                    or report["sheetSha256"] != [ref["sha256"] for ref in snapshot["images"]]
                    or report["audioSha256"]
                    != (snapshot["audio"]["sha256"] if snapshot["audio"] else None)
                    or report["continuousVisualReview"] is not False
                    or len(report["requestedSeconds"]) != (18 if snapshot["images"] else 0)
                ):
                    raise ValueError("unbound extraction report")
            except (TypeError, ValueError, KeyError):
                raise DomainError("PUBLICATION_MEDIA_REPORT_UNVERIFIED", 409) from None
            text.append(snapshot["report"])
            for image in snapshot["images"]:
                await self.artifacts.verified_path(binding["owner"], image["id"])
            if snapshot["audio"]:
                _, audio = await self.artifacts.read(binding["owner"], snapshot["audio"]["id"])
                _, raw = await self.artifacts.read(
                    binding["owner"], snapshot["transcription"]["id"]
                )
                speech = transcript_receipt(raw, audio)
                _, raw = await self.artifacts.read(binding["owner"], snapshot["transcript"]["id"])
                try:
                    matching = json.loads(raw) == {"text": speech["data"]["text"]}
                except (ValueError, TypeError):
                    matching = False
                if not matching:
                    raise DomainError("PUBLICATION_MEDIA_TRANSCRIPTION_UNVERIFIED", 409)
                text.append(snapshot["transcript"])
        text_proof = await PublicationPromptReview(self.db, self.artifacts, self.reviewer).inspect(
            binding, text
        )

        def recheck(db):
            if media_snapshot(db, binding, version_id, required) != snapshots:
                raise DomainError("PUBLICATION_MEDIA_REVIEW_CHANGED", 409)
            return reviewed_media_images(db, binding, version_id, snapshots)

        images = await self.db.call(recheck)
        return {"snapshot": snapshots, "text": text_proof, "images": images}
