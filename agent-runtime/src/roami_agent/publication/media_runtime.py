"""Resolve installed local media tools without replacing saved node configuration."""

import shutil

from roami_agent.dispatch.publication_media import PublicationMedia
from roami_agent.protocol.errors import DomainError
from roami_agent.publication.media_decode import MediaDecoder
from roami_agent.publication.media_transcription import MediaTranscription


def media_runtime(database, artifacts):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise DomainError("PUBLICATION_MEDIA_DECODER_UNAVAILABLE", 409)
    roami = shutil.which("roami")
    return PublicationMedia(
        database,
        artifacts,
        MediaDecoder(ffmpeg, ffprobe),
        MediaTranscription(roami) if roami else None,
    )
