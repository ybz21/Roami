import asyncio
import io
import os
import shutil
import subprocess
import sys

import pytest
from PIL import Image

from roami_agent.protocol.errors import DomainError
from roami_agent.publication.media_decode import MediaDecoder, streams
from roami_agent.publication.media_inspection import final_audio_duration


def probe(duration=2, kinds=("video", "audio")):
    return {
        "format": {"duration": str(duration)},
        "streams": [
            {"codec_type": kind, "width": 64, "height": 32, "duration": str(duration)}
            for kind in kinds
        ],
    }


@pytest.mark.parametrize("duration", [0, -1, "nan", "inf", 601, None])
def test_unsupported_duration_does_not_become_partial_review(duration):
    with pytest.raises(DomainError, match="PUBLICATION_MEDIA_UNSUPPORTED"):
        streams(probe(duration), "video/mp4")


@pytest.mark.parametrize(
    "kinds", [("video", "audio", "audio"), ("video", "video"), ("subtitle",), ()]
)
def test_extra_or_missing_tracks_cannot_be_silently_dropped(kinds):
    with pytest.raises(DomainError, match="PUBLICATION_MEDIA_UNSUPPORTED"):
        streams(probe(kinds=kinds), "video/mp4")


def test_fixed_inputs_disable_external_references_and_network():
    args = MediaDecoder.input("/private/source.blob", "video/mp4")
    for key, expected in (
        ("-protocol_whitelist", "file,pipe"),
        ("-format_whitelist", "mov"),
        ("-enable_drefs", "0"),
        ("-use_absolute_path", "0"),
    ):
        assert args[args.index(key) + 1] == expected
    with pytest.raises(DomainError):
        MediaDecoder.input("https://example.test/video.mp4", "video/mp4")


async def test_real_frozen_mp4_yields_actual_frame_and_full_audio(tmp_path):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg unavailable on this host")
    source = tmp_path / "source.blob"
    await asyncio.to_thread(
        subprocess.run,
        [
            ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=64x32:d=1.2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1.2",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-c:a",
            "aac",
            "-shortest",
            "-f",
            "mp4",
            str(source),
        ],
        check=True,
        timeout=20,
    )
    decoder = MediaDecoder(ffmpeg, ffprobe)
    info = await decoder.probe(source, "video/mp4")
    assert (info.width, info.height, info.has_audio) == (64, 32, True)
    assert 1 <= info.duration < 2
    frame = await decoder.frame(source, 0.6)
    with Image.open(io.BytesIO(frame)) as image:
        red, green, blue = image.convert("RGB").getpixel((5, 5))
        assert red > 200 and green < 30 and blue < 30
    audio = await decoder.audio(source, "video/mp4")
    assert audio[:4] == b"RIFF" and audio[8:12] == b"WAVE" and len(audio) > 30000
    assert abs(final_audio_duration(audio, info.audio_duration) - info.audio_duration) <= 0.1


async def test_decoder_drains_multi_chunk_output_and_limits_it(tmp_path):
    decoder = MediaDecoder(sys.executable, sys.executable)
    body = await decoder.command(
        sys.executable, ["-c", "import sys;sys.stdout.buffer.write(b'x'*150000)"], 200000
    )
    assert len(body) == 150000
    with pytest.raises(DomainError, match="PUBLICATION_MEDIA_OUTPUT_LIMIT"):
        await decoder.command(
            sys.executable, ["-c", "import sys;sys.stdout.buffer.write(b'x'*150000)"], 100000
        )


async def test_cancellation_stops_the_actual_decoder_child(tmp_path):
    decoder = MediaDecoder(sys.executable, sys.executable)
    pid = tmp_path / "child.pid"
    task = asyncio.create_task(
        decoder.command(
            sys.executable,
            ["-c", f"import os,time;open({str(pid)!r},'w').write(str(os.getpid()));time.sleep(60)"],
            100,
        )
    )
    for _ in range(100):
        if pid.exists():
            break
        await asyncio.sleep(0.01)
    assert pid.exists()
    child = int(pid.read_text())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)
