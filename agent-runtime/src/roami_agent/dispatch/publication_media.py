"""Decode only a current original-team version, with scope checked across I/O."""

import asyncio
import json
import logging
import sqlite3

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.publication.media_inspection import inspect_media
from roami_agent.publication.media_transcription import transcript_receipt
from roami_agent.storage.publication_media_reads import media_tool_artifact
from roami_agent.storage.publication_media_speech import admit_media_speech, finish_media_speech
from roami_agent.storage.publication_reviews import current_version

logger = logging.getLogger(__name__)


class PublicationMedia:
    def __init__(self, database, artifacts, decoder, transcriber=None):
        self.db, self.artifacts, self.decoder = database, artifacts, decoder
        self.transcriber = transcriber

    async def image(self, binding, version_id, artifact_id):
        await self.db.call(lambda db: current_version(db, binding, version_id))
        artifact = await self.db.call(
            lambda db: media_tool_artifact(
                db, binding["owner"], binding["conversation"], binding["turnId"], artifact_id
            )
        )
        if not artifact or artifact["mime_type"] != "image/png":
            raise DomainError("PUBLICATION_MEDIA_IMAGE_UNAVAILABLE", 409)
        source = json.loads(artifact["metadata_json"])["mediaSource"]
        if source["versionId"] != version_id:
            raise DomainError("PUBLICATION_MEDIA_IMAGE_UNAVAILABLE", 409)
        await self.artifacts.verified_path(binding["owner"], artifact_id)
        await self.db.call(lambda db: current_version(db, binding, version_id))
        return {
            "mediaImage": {
                "artifactId": artifact_id,
                "sha256": artifact["sha256"],
                "versionId": version_id,
                "sourceArtifactId": source["artifactId"],
                "sourceSha256": source["sha256"],
            },
            "publicationAuthorized": False,
        }

    async def inspect(self, binding, version_id, artifact_id):
        version, manifest = await self.db.call(lambda db: current_version(db, binding, version_id))
        selected = {
            manifest["content"][name] for name in ("video", "audio") if name in manifest["content"]
        }
        if artifact_id not in selected:
            raise DomainError("PUBLICATION_MEDIA_NOT_SELECTED", 409)
        artifact = next(item for item in manifest["artifacts"] if item["id"] == artifact_id)
        _, path = await self.artifacts.verified_path(binding["owner"], artifact_id)
        # File verification can yield while the original author or Main advances.
        await self.db.call(lambda db: current_version(db, binding, version_id))
        result = await inspect_media(self.decoder, path, artifact["mimeType"], artifact["sha256"])
        await self.artifacts.verified_path(binding["owner"], artifact_id)
        latest, _ = await self.db.call(lambda db: current_version(db, binding, version_id))
        if latest["manifest_sha256"] != version["manifest_sha256"]:
            raise DomainError("PUBLICATION_MEDIA_SOURCE_CHANGED", 409)
        return result

    async def retain(self, binding, version_id, artifact_id):
        decoded = await self.inspect(binding, version_id, artifact_id)
        metadata = {
            "kind": "publication_media",
            "mediaSource": {
                "versionId": version_id,
                "artifactId": artifact_id,
                "sha256": decoded.report["sourceSha256"],
            },
        }

        async def publish(body, name, mime):
            return await self.artifacts.put(
                binding["owner"],
                body,
                name=name,
                mime_type=mime,
                message_id=binding["assistantMessageId"],
                metadata=metadata,
            )

        sheets = [
            await publish(body, f"contact-sheet-{index + 1}.png", "image/png")
            for index, body in enumerate(decoded.sheets)
        ]
        audio = (
            await publish(decoded.audio, "final-audio.wav", "audio/wav") if decoded.audio else None
        )
        report = await publish(
            encoded(decoded.report).encode(), "media-report.json", "application/json"
        )
        await self.db.call(lambda db: current_version(db, binding, version_id))
        return {
            "versionId": version_id,
            "sourceArtifactId": artifact_id,
            "sourceSha256": decoded.report["sourceSha256"],
            "images": sheets,
            "audio": audio,
            "report": report,
            "transcriptionComplete": False,
            "publicationAuthorized": False,
        }

    async def transcribe(self, binding, version_id, artifact_id):
        if self.transcriber is None:
            raise DomainError("PUBLICATION_MEDIA_TRANSCRIPTION_UNAVAILABLE", 409)
        retained = await self.retain(binding, version_id, artifact_id)
        return await self.transcribe_retained(binding, version_id, artifact_id, retained)

    async def prepare(self, binding, version_id, artifact_id):
        retained = await self.retain(binding, version_id, artifact_id)
        if retained["audio"] is None:
            return retained
        if self.transcriber is None:
            raise DomainError("PUBLICATION_MEDIA_TRANSCRIPTION_UNAVAILABLE", 409)
        return await self.transcribe_retained(binding, version_id, artifact_id, retained)

    async def transcribe_retained(self, binding, version_id, artifact_id, retained):
        if retained["audio"] is None:
            raise DomainError("PUBLICATION_MEDIA_HAS_NO_AUDIO", 409)
        audio_ref, audio = await self.artifacts.read(binding["owner"], retained["audio"]["id"])
        payload = {
            "versionId": version_id,
            "sourceArtifactId": artifact_id,
            "sourceSha256": retained["sourceSha256"],
            "audioSha256": audio_ref["sha256"],
        }
        admitted = await self.db.call(
            lambda db: admit_media_speech(db, binding, payload), write=True
        )
        intent, result = admitted["intent"], admitted["result"]
        if admitted["fresh"]:
            try:
                speech = await self.transcriber.transcribe(audio)
                transcript_receipt(encoded(speech), audio)

                async def publish(body, name, mime):
                    return await self.artifacts.put(
                        binding["owner"],
                        body,
                        name=name,
                        mime_type=mime,
                        message_id=binding["assistantMessageId"],
                        metadata=audio_ref["metadata"],
                    )

                response = await publish(
                    encoded(speech).encode(), "speech-response.json", "application/json"
                )
                text = await publish(
                    encoded({"text": speech["data"]["text"]}).encode(),
                    "transcript.json",
                    "application/json",
                )
                result = await self.db.call(
                    lambda db: finish_media_speech(
                        db,
                        binding["owner"],
                        intent,
                        {"state": "succeeded", "response": response, "transcript": text},
                    ),
                    write=True,
                )
            except BaseException as exc:
                failure = {
                    "state": "unknown",
                    "errorCode": getattr(exc, "code", type(exc).__name__),
                }
                try:
                    await asyncio.shield(
                        self.db.call(
                            lambda db: finish_media_speech(db, binding["owner"], intent, failure),
                            write=True,
                        )
                    )
                except (DomainError, sqlite3.Error, RuntimeError) as storage_error:
                    logger.warning(
                        "Speech result unrecorded; intent retained (%s)",
                        type(storage_error).__name__,
                    )
                raise
        if not result or result.get("state") != "succeeded":
            raise DomainError("PUBLICATION_MEDIA_TRANSCRIPTION_OUTCOME_UNKNOWN", 409)
        _, response_bytes = await self.artifacts.read(binding["owner"], result["response"]["id"])
        _, text_bytes = await self.artifacts.read(binding["owner"], result["transcript"]["id"])
        speech = transcript_receipt(response_bytes, audio)
        if json.loads(text_bytes) != {"text": speech["data"]["text"]}:
            raise DomainError("PUBLICATION_MEDIA_TRANSCRIPTION_UNVERIFIED", 409)
        await self.db.call(lambda db: current_version(db, binding, version_id))
        return {
            **retained,
            "speechIntentId": intent["id"],
            "transcription": result["response"],
            "transcript": result["transcript"],
            "transcriptionComplete": True,
        }
