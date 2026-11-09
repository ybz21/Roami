"""Decode frozen local MP4/WAV bytes with fixed formats and no external tracks."""

import asyncio
import json
import math
from dataclasses import dataclass
from pathlib import Path

from roami_agent.protocol.errors import DomainError


@dataclass(frozen=True)
class MediaStreams:
    duration: float
    width: int
    height: int
    has_audio: bool
    audio_duration: float | None = None


def streams(payload, mime):
    try:
        duration = float(payload["format"]["duration"])
        items = payload["streams"]
        video = [s for s in items if s["codec_type"] == "video"]
        audio = [s for s in items if s["codec_type"] == "audio"]
        if any(s["codec_type"] not in {"video", "audio"} for s in items):
            raise ValueError("additional streams")
        if not math.isfinite(duration) or not 0 < duration <= 600:
            raise ValueError("duration")
        if mime == "video/mp4":
            if len(video) != 1 or len(audio) > 1:
                raise ValueError("ambiguous streams")
            width, height = video[0]["width"], video[0]["height"]
            if type(width) is not int or type(height) is not int:
                raise ValueError("dimensions")
            if width <= 0 or height <= 0 or width * height > 4096 * 2304:
                raise ValueError("dimensions")
        elif mime in {"audio/wav", "audio/x-wav"} and len(audio) == 1 and not video:
            width, height = 0, 0
        else:
            raise ValueError("format")
        audio_duration = float(audio[0]["duration"]) if audio else None
        if audio_duration is not None and (
            not math.isfinite(audio_duration) or not 0 < audio_duration <= 600
        ):
            raise ValueError("audio duration")
        return MediaStreams(duration, width, height, bool(audio), audio_duration)
    except (KeyError, TypeError, ValueError, OverflowError):
        raise DomainError("PUBLICATION_MEDIA_UNSUPPORTED", 409) from None


class MediaDecoder:
    def __init__(self, ffmpeg, ffprobe):
        self.ffmpeg = str(Path(ffmpeg).resolve(strict=True))
        self.ffprobe = str(Path(ffprobe).resolve(strict=True))

    @staticmethod
    def input(path, mime):
        source = Path(path)
        if not source.is_absolute() or mime not in {"video/mp4", "audio/wav", "audio/x-wav"}:
            raise DomainError("PUBLICATION_MEDIA_UNSUPPORTED", 409)
        result = ["-protocol_whitelist", "file,pipe"]
        if mime == "video/mp4":
            result += [
                "-format_whitelist",
                "mov",
                "-f",
                "mov",
                "-enable_drefs",
                "0",
                "-use_absolute_path",
                "0",
            ]
        else:
            result += ["-format_whitelist", "wav", "-f", "wav"]
        return [*result, "-i", str(source)]

    async def command(self, executable, arguments, limit):
        process = await asyncio.create_subprocess_exec(
            executable,
            *arguments,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(45):
                body = bytearray()
                while chunk := await process.stdout.read(min(65536, limit + 1 - len(body))):
                    body.extend(chunk)
                    if len(body) > limit:
                        raise DomainError("PUBLICATION_MEDIA_OUTPUT_LIMIT", 409)
                if await process.wait() != 0:
                    raise DomainError("PUBLICATION_MEDIA_DECODE_FAILED", 409)
                return bytes(body)
        except TimeoutError:
            raise DomainError("PUBLICATION_MEDIA_DECODE_TIMEOUT", 409) from None
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await process.wait()

    async def probe(self, path, mime):
        body = await self.command(
            self.ffprobe,
            [
                "-v",
                "error",
                *self.input(path, mime),
                "-show_entries",
                "format=duration:stream=codec_type,width,height,duration",
                "-of",
                "json",
            ],
            65536,
        )
        try:
            return streams(json.loads(body), mime)
        except (ValueError, UnicodeError):
            raise DomainError("PUBLICATION_MEDIA_DECODE_FAILED", 409) from None

    async def frame(self, path, seconds):
        if not math.isfinite(seconds) or seconds < 0:
            raise DomainError("PUBLICATION_MEDIA_SAMPLE_INVALID", 409)
        return await self.command(
            self.ffmpeg,
            [
                "-v",
                "error",
                "-nostdin",
                "-xerror",
                "-threads",
                "1",
                "-ss",
                f"{seconds:.6f}",
                *self.input(path, "video/mp4"),
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-vf",
                "scale=640:640:force_original_aspect_ratio=decrease",
                "-threads",
                "1",
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "pipe:1",
            ],
            4 << 20,
        )

    async def audio(self, path, mime):
        return await self.command(
            self.ffmpeg,
            [
                "-v",
                "error",
                "-nostdin",
                "-xerror",
                "-threads",
                "1",
                *self.input(path, mime),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                "-threads",
                "1",
                "-f",
                "wav",
                "pipe:1",
            ],
            25 << 20,
        )
