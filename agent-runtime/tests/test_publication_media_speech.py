import asyncio
import hashlib
import json

import pytest
from test_publication_media_inspection import Decoder
from test_publication_media_scope import media_fixture
from test_publication_media_transcription import AUDIO
from test_swarm_coordination import coordination as coordination_fixture
from test_swarm_delegations import delegated_team as delegated_team_fixture

from roami_agent.dispatch.publication_media import PublicationMedia
from roami_agent.protocol.errors import DomainError
from roami_agent.publication.media_decode import MediaStreams
from roami_agent.storage.publication_media_speech import admit_media_speech

coordination = coordination_fixture
delegated_team = delegated_team_fixture


class AudioDecoder(Decoder):
    async def probe(self, path, mime):
        return (
            MediaStreams(18, 0, 0, True, 1)
            if mime.startswith("audio/")
            else MediaStreams(18, 64, 32, True, 1)
        )

    async def audio(self, path, mime):
        return AUDIO


class Speech:
    def __init__(self, hook=None, text="Actual fixture final-track transcript"):
        self.calls, self.hook = 0, hook
        self.text = text

    async def transcribe(self, audio):
        self.calls += 1
        if self.hook:
            await self.hook()
        data = {"text": self.text}
        body = json.dumps({"data": data})
        return {
            "input": {"sha256": hashlib.sha256(audio).hexdigest(), "bytes": len(audio)},
            "response": {
                "status": 200,
                "body": body,
                "sha256": hashlib.sha256(body.encode()).hexdigest(),
            },
            "data": data,
        }


async def test_recovered_service_reuses_durable_speech_result_without_upload(coordination):
    runtime, binding, _, version, media, _ = await media_fixture(coordination)
    speech = Speech()
    first = await PublicationMedia(
        runtime.db, runtime.artifacts, AudioDecoder(), speech
    ).transcribe(binding, version["versionId"], media["id"])
    recovered = Speech()
    second = await PublicationMedia(
        runtime.db, runtime.artifacts, AudioDecoder(), recovered
    ).transcribe(binding, version["versionId"], media["id"])
    assert speech.calls == 1 and recovered.calls == 0
    assert first == second and first["transcriptionComplete"] is True
    assert first["publicationAuthorized"] is False
    assert (
        await runtime.db.call(
            lambda db: db.execute("SELECT count(*) FROM swarm_publication_reviews").fetchone()[0]
        )
        == 0
    )


@pytest.mark.parametrize("text", ["", "最终音轨\n中文与 English"])
async def test_empty_and_multilingual_transcripts_keep_readable_exact_evidence(coordination, text):
    runtime, binding, _, version, media, _ = await media_fixture(coordination)
    result = await PublicationMedia(
        runtime.db, runtime.artifacts, AudioDecoder(), Speech(text=text)
    ).transcribe(binding, version["versionId"], media["id"])
    reference, body = await runtime.artifacts.read("alice", result["transcript"]["id"])
    assert reference["sizeBytes"] > 0 and json.loads(body) == {"text": text}


async def test_concurrent_main_calls_share_one_durable_intent(coordination):
    runtime, binding, _, version, media, _ = await media_fixture(coordination)
    entered, release = asyncio.Event(), asyncio.Event()

    async def waiting():
        entered.set()
        await release.wait()

    speech = Speech(waiting)
    service = PublicationMedia(runtime.db, runtime.artifacts, AudioDecoder(), speech)
    task = asyncio.create_task(service.transcribe(binding, version["versionId"], media["id"]))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        with pytest.raises(DomainError, match="PUBLICATION_MEDIA_TRANSCRIPTION_OUTCOME_UNKNOWN"):
            await service.transcribe(binding, version["versionId"], media["id"])
        assert speech.calls == 1
    finally:
        release.set()
        await task


async def test_failed_transcription_cannot_be_replayed_after_recovery(coordination):
    runtime, binding, _, version, media, _ = await media_fixture(coordination)

    async def failure():
        raise DomainError("PUBLICATION_MEDIA_TRANSCRIPTION_OUTCOME_UNKNOWN", 409)

    speech = Speech(failure)
    service = PublicationMedia(runtime.db, runtime.artifacts, AudioDecoder(), speech)
    for _ in range(2):
        with pytest.raises(DomainError, match="PUBLICATION_MEDIA_TRANSCRIPTION_OUTCOME_UNKNOWN"):
            await service.transcribe(binding, version["versionId"], media["id"])
    assert speech.calls == 1


async def test_revoked_goal_retains_speech_fact_without_granting_review(coordination):
    runtime, binding, scope, version, media, _ = await media_fixture(coordination)

    async def revoke():
        await runtime.db.call(
            lambda db: db.execute(
                "UPDATE swarm_goal_delegations SET revoked_ms=1,revoked_by_message_id=source_message_id WHERE id=?",
                (scope["delegationId"],),
            ),
            write=True,
        )

    speech = Speech(revoke)
    with pytest.raises(DomainError):
        await PublicationMedia(runtime.db, runtime.artifacts, AudioDecoder(), speech).transcribe(
            binding, version["versionId"], media["id"]
        )
    assert speech.calls == 1
    results = await runtime.db.call(
        lambda db: [
            json.loads(r[0])
            for r in db.execute(
                "SELECT receipt_json FROM swarm_commands WHERE command_key LIKE 'publication-media-speech-result:%'"
            )
        ]
    )
    assert len(results) == 1 and results[0]["state"] == "succeeded"
    assert results[0]["publicationAuthorized"] is False


async def test_committed_intent_without_result_is_not_replayed_after_restart(coordination):
    runtime, binding, _, version, media, _ = await media_fixture(coordination)
    speech = Speech()
    service = PublicationMedia(runtime.db, runtime.artifacts, AudioDecoder(), speech)
    retained = await service.retain(binding, version["versionId"], media["id"])
    payload = {
        "versionId": version["versionId"],
        "sourceArtifactId": media["id"],
        "sourceSha256": media["sha256"],
        "audioSha256": retained["audio"]["sha256"],
    }
    await runtime.db.call(lambda db: admit_media_speech(db, binding, payload), write=True)
    with pytest.raises(DomainError, match="PUBLICATION_MEDIA_TRANSCRIPTION_OUTCOME_UNKNOWN"):
        await service.transcribe(binding, version["versionId"], media["id"])
    assert speech.calls == 0


async def test_cancelled_speech_call_keeps_intent_instead_of_reuploading(coordination):
    runtime, binding, _, version, media, _ = await media_fixture(coordination)
    entered = asyncio.Event()

    async def waiting():
        entered.set()
        await asyncio.Event().wait()

    speech = Speech(waiting)
    service = PublicationMedia(runtime.db, runtime.artifacts, AudioDecoder(), speech)
    task = asyncio.create_task(service.transcribe(binding, version["versionId"], media["id"]))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(DomainError, match="PUBLICATION_MEDIA_TRANSCRIPTION_OUTCOME_UNKNOWN"):
        await service.transcribe(binding, version["versionId"], media["id"])
    assert speech.calls == 1
