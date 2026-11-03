"""Decode selected frames against their presentation timestamps."""

import hashlib
import io
import json
import math
import subprocess
from itertools import pairwise

from PIL import Image
from video_workspace import MediaError


def command(args):
    result = subprocess.run(args, capture_output=True, check=False)
    if result.returncode:
        raise MediaError(
            "MEDIA_COMMAND_FAILED: " + result.stderr.decode(errors="replace")[-2000:]
        )
    return result.stdout


def timeline(path):
    info = json.loads(
        command(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-f",
                "mov",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=duration:frame=best_effort_timestamp_time,duration_time,pkt_duration_time",
                "-of",
                "json",
                str(path),
            ]
        )
    )
    try:
        times = [float(frame["best_effort_timestamp_time"]) for frame in info["frames"]]
    except (KeyError, IndexError, TypeError, ValueError):
        raise MediaError("VIDEO_TIMELINE_REQUIRED") from None
    if not times:
        raise MediaError("VIDEO_TIMELINE_REQUIRED")
    if not all(math.isfinite(t) for t in times) or any(
        a >= b for a, b in pairwise(times)
    ):
        raise MediaError("VIDEO_TIMELINE_INVALID")

    def positive(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) and number > 0 else None

    declared = positive(info.get("streams", [{}])[0].get("duration"))
    last = info["frames"][-1]
    dwell = positive(last.get("duration_time")) or positive(
        last.get("pkt_duration_time")
    )
    end = times[-1] - times[0] + (dwell or 0)
    duration = max(declared or 0, end)
    if duration <= 0:
        raise MediaError("VIDEO_TIMELINE_REQUIRED")
    return (
        duration,
        times,
        {
            "declaredDurationSeconds": declared,
            "lastFrameDurationSeconds": dwell,
            "decodedEndSeconds": end,
        },
    )


def samples(path, fractions):
    duration, times, timing = timeline(path)
    requests = {}
    for fraction in fractions:
        seconds = fraction * duration
        index = min(range(len(times)), key=lambda i: abs(times[i] - times[0] - seconds))
        requests.setdefault(index, []).append(
            {"fraction": fraction, "seconds": seconds}
        )
    selected = []
    for index in sorted(requests):
        body = command(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-f",
                "mov",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-vf",
                rf"select=eq(n\,{index}),scale=w='min(1280,iw)':h='min(1280,ih)':force_original_aspect_ratio=decrease",
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "pipe:1",
            ]
        )
        with Image.open(io.BytesIO(body)) as image:
            picture = image.convert("RGB")
        selected.append(
            (
                picture,
                {
                    "frameIndex": index,
                    "seconds": times[index] - times[0],
                    "sourceTimestamp": times[index],
                    "requests": requests[index],
                    "decodedPngSha256": hashlib.sha256(body).hexdigest(),
                    "width": picture.width,
                    "height": picture.height,
                },
            )
        )
    return duration, times[0], len(times), selected, timing
