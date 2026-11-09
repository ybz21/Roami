import hashlib
import io

import pytest
from PIL import Image

from roami_agent.protocol.errors import DomainError
from roami_agent.publication.media_decode import MediaStreams
from roami_agent.publication.media_inspection import (
    contact_sheets,
    final_audio_duration,
    inspect_media,
    source_identity,
)


def png(color):
    output = io.BytesIO()
    Image.new("RGB", (64, 32), color).save(output, "PNG")
    return output.getvalue()


class Decoder:
    def __init__(self, *, change=None, malformed_audio=False):
        self.change = change
        self.malformed_audio = malformed_audio
        self.positions = []

    async def probe(self, path, mime):
        return MediaStreams(18, 64, 32, self.malformed_audio)

    async def frame(self, path, seconds):
        self.positions.append(seconds)
        if self.change and len(self.positions) == 9:
            path.write_bytes(b"changed source")
        return png("red")

    async def audio(self, path, mime):
        return b"not a complete WAV"


async def test_samples_are_explicit_and_dont_claim_full_playback_or_approval(tmp_path):
    source = tmp_path / "frozen.blob"
    source.write_bytes(b"fixed test source")
    decoder = Decoder()
    result = await inspect_media(
        decoder, source, "video/mp4", hashlib.sha256(source.read_bytes()).hexdigest()
    )
    assert decoder.positions == [index + 0.5 for index in range(18)]
    assert result.report["continuousVisualReview"] is False
    assert result.report["publicationAuthorized"] is False
    assert result.report["transcriptionComplete"] is False
    assert result.report["audioExtraction"] == "no audio track" and result.audio is None
    assert len(result.sheets) == 3
    for sheet in result.sheets:
        with Image.open(io.BytesIO(sheet)) as image:
            assert image.size == (1920, 1328)
            assert image.getpixel((320, 320)) == (255, 0, 0)


async def test_source_changes_during_decode_cannot_produce_review_evidence(tmp_path):
    source = tmp_path / "frozen.blob"
    source.write_bytes(b"fixed test source")
    with pytest.raises(DomainError, match="PUBLICATION_MEDIA_SOURCE_CHANGED"):
        await inspect_media(
            Decoder(change=True),
            source,
            "video/mp4",
            hashlib.sha256(source.read_bytes()).hexdigest(),
        )


async def test_partial_audio_cannot_be_marked_complete(tmp_path):
    source = tmp_path / "frozen.blob"
    source.write_bytes(b"fixed test source")
    with pytest.raises(DomainError, match="PUBLICATION_MEDIA_AUDIO_INCOMPLETE"):
        await inspect_media(
            Decoder(malformed_audio=True),
            source,
            "video/mp4",
            hashlib.sha256(source.read_bytes()).hexdigest(),
        )


@pytest.mark.parametrize("count", [0, 1, 17, 19])
def test_partial_frame_sets_cannot_hide_missing_samples(count):
    with pytest.raises(DomainError, match="PUBLICATION_MEDIA_FRAMES_INCOMPLETE"):
        contact_sheets([png("red")] * count, list(range(count)))


def test_symlink_is_not_admitted_as_the_frozen_source(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"source")
    link = tmp_path / "alias"
    link.symlink_to(source)
    with pytest.raises(DomainError, match="PUBLICATION_MEDIA_SOURCE_UNAVAILABLE"):
        source_identity(link)


@pytest.mark.parametrize("fault", ["truncated", "rate", "stereo", "unknown"])
def test_audio_completion_requires_actual_pcm_format_and_source_duration(fault):
    import wave

    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams(
            (
                2 if fault == "stereo" else 1,
                2,
                8000 if fault == "rate" else 16000,
                0,
                "NONE",
                "not compressed",
            )
        )
        wav.writeframes(b"\x00\x00" * 16000)
    body = output.getvalue()
    if fault == "truncated":
        body = body[:-16000]
    with pytest.raises(DomainError, match="PUBLICATION_MEDIA_AUDIO_INCOMPLETE"):
        final_audio_duration(body, None if fault == "unknown" else 1)
