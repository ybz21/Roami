"""Transcribe final extracted audio once through the node's saved speech service."""

import asyncio
import hashlib
import json
import tempfile
from pathlib import Path

from roami_agent.protocol.errors import DomainError


def transcript_receipt(raw, audio):
    try:
        receipt = json.loads(raw)
        response = receipt["response"]
        if not isinstance(response["body"], str):
            raise TypeError("invalid speech body")
        body = response["body"].encode("utf-8")
        data = json.loads(body)["data"]
        if (
            receipt.get("error")
            or receipt["input"]
            != {"sha256": hashlib.sha256(audio).hexdigest(), "bytes": len(audio)}
            or response["status"] != 200
            or response.get("truncated", False) is not False
            or hashlib.sha256(body).hexdigest() != response["sha256"]
            or receipt["data"] != data
            or not isinstance(data["text"], str)
        ):
            raise ValueError("incomplete speech evidence")
        return receipt
    except (KeyError, TypeError, ValueError, UnicodeError):
        raise DomainError("PUBLICATION_MEDIA_TRANSCRIPTION_UNVERIFIED", 409) from None


class MediaTranscription:
    def __init__(self, roami):
        self.roami = str(Path(roami).resolve(strict=True))

    async def transcribe(self, audio):
        if (
            not isinstance(audio, bytes)
            or not 44 < len(audio) <= 25 << 20
            or audio[:4] != b"RIFF"
            or audio[8:12] != b"WAVE"
        ):
            raise DomainError("PUBLICATION_MEDIA_AUDIO_INCOMPLETE", 409)
        digest = hashlib.sha256(audio).hexdigest()
        with tempfile.TemporaryDirectory(prefix="roami-media-audio-") as directory:
            path = Path(directory) / "final.wav"
            path.write_bytes(audio)
            path.chmod(0o400)
            process = await asyncio.create_subprocess_exec(
                self.roami,
                "speech",
                "transcribe",
                "--file",
                str(path),
                "--file-root",
                directory,
                "--expected-file-sha256",
                digest,
                "--json",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                async with asyncio.timeout(130):
                    body = bytearray()
                    while chunk := await process.stdout.read(65536):
                        body.extend(chunk)
                        if len(body) > 2 << 20:
                            raise DomainError("PUBLICATION_MEDIA_TRANSCRIPTION_UNVERIFIED", 409)
                    if await process.wait() != 0:
                        raise DomainError("PUBLICATION_MEDIA_TRANSCRIPTION_UNAVAILABLE", 409)
                    return transcript_receipt(body, audio)
            except TimeoutError:
                raise DomainError("PUBLICATION_MEDIA_TRANSCRIPTION_OUTCOME_UNKNOWN", 409) from None
            finally:
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                await process.wait()
