"""Join complete chosen clips with one bounded timeline and a matching JSON manifest."""

import argparse
import json
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

from video_workspace import MediaError, Workspace


def run(args):
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode:
        raise MediaError("MEDIA_COMMAND_FAILED: " + result.stderr[-2000:])
    return result.stdout


def probe(path, count=False):
    return json.loads(
        run(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-f",
                "mov",
                *(["-count_frames"] if count else []),
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ]
        )
    )


def positive(value):
    if type(value) not in (int, float, str):
        raise MediaError("POSITIVE_NUMBER_REQUIRED")
    try:
        number = Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        raise MediaError("POSITIVE_NUMBER_REQUIRED") from None
    if number <= 0:
        raise MediaError("POSITIVE_NUMBER_REQUIRED")
    return number


def ceiling(value):
    return -(-value.numerator // value.denominator)


def assemble(workspace, spec):
    if not isinstance(spec, dict) or set(spec) - {
        "inputs",
        "video",
        "manifest",
        "fps",
        "width",
        "height",
    }:
        raise MediaError("SPEC_INVALID")
    if not isinstance(spec.get("inputs"), list) or not spec["inputs"]:
        raise MediaError("INPUTS_REQUIRED")
    if not all(isinstance(spec.get(k), str) and spec[k] for k in ["video", "manifest"]):
        raise MediaError("OUTPUT_PATHS_REQUIRED")
    if workspace.path(spec["video"], exists=False) == workspace.path(
        spec["manifest"], exists=False
    ):
        raise MediaError("OUTPUT_PATHS_DUPLICATE")
    for name in [spec["video"], spec["manifest"]]:
        if workspace.path(name, exists=False).exists():
            raise MediaError("OUTPUT_EXISTS")
    if (
        Path(spec["video"]).suffix.lower() != ".mp4"
        or Path(spec["manifest"]).suffix.lower() != ".json"
    ):
        raise MediaError("OUTPUT_FORMAT_INVALID")
    with tempfile.TemporaryDirectory(
        prefix=".video-assembly-", dir=workspace.root
    ) as tmp:
        temp = Path(tmp)
        sources = []
        clips = []
        ids = set()
        for index, item in enumerate(spec["inputs"]):
            if (
                not isinstance(item, dict)
                or set(item) - {"path", "sha256", "id"}
                or not isinstance(item.get("path"), str)
            ):
                raise MediaError("INPUT_INVALID")
            ident = item.get("id", Path(item["path"]).stem)
            if not isinstance(ident, str) or not ident or ident in ids:
                raise MediaError("SOURCE_IDS_INVALID")
            ids.add(ident)
            snapshot = temp / f"clip-{index}.mp4"
            sources.append(
                workspace.snapshot(item["path"], snapshot, item.get("sha256"))
            )
            info = probe(snapshot)
            streams = info.get("streams", [])
            video = next((v for v in streams if v.get("codec_type") == "video"), None)
            if not video:
                raise MediaError("VIDEO_STREAM_REQUIRED")
            duration = positive(info.get("format", {}).get("duration"))
            clips.append(
                {
                    "id": ident,
                    "file": snapshot,
                    "video": video,
                    "audio": any(v.get("codec_type") == "audio" for v in streams),
                    "duration": duration,
                }
            )
        fps = positive(spec.get("fps", clips[0]["video"].get("avg_frame_rate", "30")))
        width = spec.get("width", clips[0]["video"].get("width"))
        height = spec.get("height", clips[0]["video"].get("height"))
        if (
            type(width) is not int
            or type(height) is not int
            or min(width, height) < 2
            or width % 2
            or height % 2
        ):
            raise MediaError("EVEN_DIMENSIONS_REQUIRED")
        args = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
        filters = []
        segments = []
        total = 0
        for index, clip in enumerate(clips):
            args += [
                "-protocol_whitelist",
                "file,pipe",
                "-f",
                "mov",
                "-i",
                str(clip["file"]),
            ]
            frames = ceiling(clip["duration"] * fps)
            duration = Fraction(frames, 1) / fps
            samples = ceiling(duration * 48000)
            filters.append(
                f"[{index}:v:0]fps={fps}:start_time=0,scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,tpad=stop_mode=clone:stop_duration={float(duration):.12f},trim=end_frame={frames},setpts=PTS-STARTPTS[v{index}]"
            )
            audio = (
                f"[{index}:a:0]aresample=48000:first_pts=0,aformat=sample_fmts=fltp:channel_layouts=stereo,apad"
                if clip["audio"]
                else "anullsrc=r=48000:cl=stereo"
            )
            filters.append(
                audio + f",atrim=end_sample={samples},asetpts=PTS-STARTPTS[a{index}]"
            )
            segments.append(
                {
                    "source": clip["id"],
                    "source_range": [0, float(clip["duration"])],
                    "output": [
                        float(Fraction(total, 1) / fps),
                        float(Fraction(total + frames, 1) / fps),
                    ],
                }
            )
            total += frames
        filters.append(
            "".join(f"[v{i}][a{i}]" for i in range(len(clips)))
            + f"concat=n={len(clips)}:v=1:a=1[outv][outa]"
        )
        video = temp / "sequence.mp4"
        args += [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[outv]",
            "-map",
            "[outa]",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(video),
        ]
        run(args)
        actual = probe(video, count=True)
        stream = next(v for v in actual["streams"] if v["codec_type"] == "video")
        audio = next(v for v in actual["streams"] if v["codec_type"] == "audio")
        expected = float(Fraction(total, 1) / fps)
        if (
            int(stream.get("nb_read_frames", -1)) != total
            or abs(float(stream["duration"]) - expected) > float(1 / fps) + 0.001
            or abs(float(audio["duration"]) - expected) > 0.05
        ):
            raise MediaError("TIMELINE_VERIFICATION_FAILED")
        manifest = temp / "sequence.json"
        manifest.write_text(json.dumps({"segments": segments}, indent=2) + "\n")
        published = workspace.publish(
            {spec["video"]: video, spec["manifest"]: manifest}, sources
        )
        return {
            "inputs": sources,
            "outputs": published,
            "segments": segments,
            "frames": total,
            "fps": str(fps),
            "duration": expected,
            "width": width,
            "height": height,
            "audioRate": 48000,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--spec", required=True)
    args = parser.parse_args()
    try:
        workspace = Workspace(args.workspace)
        spec = json.loads(workspace.path(args.spec).read_text())
        result = assemble(workspace, spec)
    except (MediaError, OSError, ValueError, KeyError, StopIteration) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
