"""Sample immutable media and retain complete final audio without approving publication."""

import asyncio
import hashlib
import io
import os
import stat
import wave
from dataclasses import dataclass

from PIL import Image, ImageDraw

from roami_agent.protocol.errors import DomainError


def source_identity(path):
    try:
        with open(
            os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb", closefd=True
        ) as file:
            before = os.fstat(file.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > 200 << 20:
                raise DomainError("PUBLICATION_MEDIA_SOURCE_UNAVAILABLE", 409)
            digest = hashlib.file_digest(file, "sha256").hexdigest()
            after = os.fstat(file.fileno())
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise DomainError("PUBLICATION_MEDIA_SOURCE_CHANGED", 409)
            return (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ), digest
    except OSError:
        raise DomainError("PUBLICATION_MEDIA_SOURCE_UNAVAILABLE", 409) from None


def contact_sheets(frames, requested_seconds):
    if len(frames) != 18 or len(requested_seconds) != 18:
        raise DomainError("PUBLICATION_MEDIA_FRAMES_INCOMPLETE", 409)
    sheets = []
    for start in range(0, 18, 6):
        canvas = Image.new("RGB", (1920, 1328), "black")
        draw = ImageDraw.Draw(canvas)
        for index in range(start, start + 6):
            try:
                with Image.open(io.BytesIO(frames[index])) as image:
                    if (
                        image.format != "PNG"
                        or not 0 < image.width <= 640
                        or not 0 < image.height <= 640
                    ):
                        raise ValueError("frame dimensions")
                    image.load()
                    tile = image.convert("RGB")
            except (OSError, ValueError):
                raise DomainError("PUBLICATION_MEDIA_FRAMES_INCOMPLETE", 409) from None
            x, y = (index % 3) * 640, ((index - start) // 3) * 664
            canvas.paste(tile, (x + (640 - tile.width) // 2, y + (640 - tile.height) // 2))
            draw.text(
                (x + 8, y + 642),
                f"Frame {index + 1:02d} / requested {requested_seconds[index]:.3f}s",
                fill="white",
            )
        output = io.BytesIO()
        canvas.save(output, "PNG")
        sheets.append(output.getvalue())
    return sheets


def final_audio_duration(audio, expected):
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (
                1,
                2,
                16000,
                "NONE",
            ):
                raise ValueError("unexpected PCM format")
            pcm = wav.readframes(16000 * 601)
        duration = len(pcm) / 32000
        if not pcm or len(pcm) % 2 or expected is None or abs(duration - expected) > 0.1:
            raise ValueError("incomplete final audio")
        return duration
    except (EOFError, OSError, ValueError, wave.Error):
        raise DomainError("PUBLICATION_MEDIA_AUDIO_INCOMPLETE", 409) from None


@dataclass(frozen=True)
class DecodedMedia:
    report: dict
    sheets: list[bytes]
    audio: bytes | None


async def inspect_media(decoder, path, mime, expected_sha256):
    before, digest = await asyncio.to_thread(source_identity, path)
    if digest != expected_sha256:
        raise DomainError("PUBLICATION_MEDIA_SOURCE_CHANGED", 409)
    try:
        async with asyncio.timeout(180):
            info = await decoder.probe(path, mime)
            requested = (
                [info.duration * (index + 0.5) / 18 for index in range(18)] if info.width else []
            )
            frames = [await decoder.frame(path, seconds) for seconds in requested]
            audio = await decoder.audio(path, mime) if info.has_audio else None
            sheets = await asyncio.to_thread(contact_sheets, frames, requested) if frames else []
    except TimeoutError:
        raise DomainError("PUBLICATION_MEDIA_INSPECTION_TIMEOUT", 409) from None
    audio_duration = final_audio_duration(audio, info.audio_duration) if audio is not None else None
    after, current = await asyncio.to_thread(source_identity, path)
    if before != after or current != expected_sha256:
        raise DomainError("PUBLICATION_MEDIA_SOURCE_CHANGED", 409)
    return DecodedMedia(
        report={
            "sourceSha256": expected_sha256,
            "durationSeconds": info.duration,
            "sampleMethod": "18 uniform requested positions" if frames else "audio only",
            "continuousVisualReview": False,
            "requestedSeconds": requested,
            "sheetSha256": [hashlib.sha256(value).hexdigest() for value in sheets],
            "audioSha256": hashlib.sha256(audio).hexdigest() if audio else None,
            "audioDurationSeconds": audio_duration,
            "audioExpectedDurationSeconds": info.audio_duration,
            "audioExtraction": "complete final source track, mono PCM16 16000Hz"
            if audio
            else "no audio track",
            "transcriptionComplete": False,
            "publicationAuthorized": False,
        },
        sheets=sheets,
        audio=audio,
    )
