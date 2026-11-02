"""Exercise actual video/audio timelines, source preservation and guarded publication."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from assemble import assemble, probe
from video_workspace import MediaError, Workspace, sha256


@pytest.fixture(scope="session")
def clips(tmp_path_factory):
    root = tmp_path_factory.mktemp("clips")
    recipe = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "cases/case-72-mech-va01/input/recipe.json"
        ).read_text()
    )
    for clip in recipe["clips"]:
        args = [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color={clip['color']}:s=80x60:r={clip['fps']}:d={clip['videoSeconds']}",
        ]
        if clip["audioSeconds"]:
            args += [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:sample_rate=44100:duration={clip['audioSeconds']}",
            ]
        args += (
            ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
            + (["-c:a", "aac"] if clip["audioSeconds"] else [])
            + [str(root / (clip["name"] + ".mp4"))]
        )
        subprocess.run(args, check=True, capture_output=True)
    return root, recipe


@pytest.fixture
def source(tmp_path, clips):
    root, recipe = clips
    inputs = tmp_path / "input"
    inputs.mkdir()
    items = []
    for clip in recipe["clips"]:
        target = inputs / (clip["name"] + ".mp4")
        target.write_bytes((root / target.name).read_bytes())
        items.append(
            {"path": str(target.relative_to(tmp_path)), "sha256": sha256(target)}
        )
    return (
        Workspace(tmp_path),
        {
            "inputs": items,
            "video": "output/sequence.mp4",
            "manifest": "output/sequence.json",
        },
        recipe,
    )


def test_mixed_rates_and_missing_audio_have_one_verified_timeline(source):
    workspace, spec, recipe = source
    receipt = assemble(workspace, spec)
    assert (
        receipt["frames"] == recipe["expectedDefaultFrames"] and receipt["fps"] == "24"
    )
    assert [x["source"] for x in receipt["segments"]] == recipe["expectedSources"]
    assert receipt["segments"][0]["output"][0] == 0
    assert all(
        a["output"][1] == b["output"][0]
        for a, b in zip(receipt["segments"], receipt["segments"][1:])
    )
    for segment, index in zip(receipt["segments"], [0, 2, 1], strict=True):
        pixel = subprocess.check_output(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                str(sum(segment["output"]) / 2),
                "-i",
                str(workspace.root / spec["video"]),
                "-vf",
                "scale=1:1",
                "-frames:v",
                "1",
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                "-",
            ]
        )
        assert len(pixel) == 3 and pixel[index] == max(pixel)
    assert all(
        sha256(workspace.root / x["path"]) == x["sha256"] for x in spec["inputs"]
    )
    assert json.loads((workspace.root / spec["manifest"]).read_text()) == {
        "segments": receipt["segments"]
    }
    assert all(
        sha256(workspace.root / x["path"]) == x["sha256"] for x in receipt["outputs"]
    )


def test_fractional_output_rate_is_verified_by_decoded_frames(source):
    workspace, spec, _ = source
    spec["fps"] = "30000/1001"
    receipt = assemble(workspace, spec)
    info = probe(workspace.root / spec["video"], count=True)
    stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (
        receipt["fps"] == "30000/1001"
        and int(stream["nb_read_frames"]) == receipt["frames"]
    )


def test_one_complete_silent_clip_can_be_assembled(source):
    workspace, spec, _ = source
    spec["inputs"] = spec["inputs"][-1:]
    receipt = assemble(workspace, spec)
    assert len(receipt["segments"]) == 1 and receipt["segments"][0]["source"] == "green"
    assert receipt["audioRate"] == 48000


@pytest.mark.parametrize("field", ["video", "manifest"])
def test_existing_output_is_never_overwritten(source, field):
    workspace, spec, _ = source
    path = workspace.root / spec[field]
    path.parent.mkdir()
    path.write_bytes(b"keep")
    with pytest.raises(MediaError, match="OUTPUT_EXISTS"):
        assemble(workspace, spec)
    assert path.read_bytes() == b"keep"


def test_changed_source_is_rejected_before_any_output(source):
    workspace, spec, _ = source
    (workspace.root / spec["inputs"][0]["path"]).write_bytes(b"changed")
    with pytest.raises(MediaError, match="SOURCE_CHANGED"):
        assemble(workspace, spec)
    assert not (workspace.root / "output").exists()


@pytest.mark.parametrize("kind", ["parent", "absolute", "symlink", "directory"])
def test_invalid_input_scope_cannot_be_read(source, kind, tmp_path):
    workspace, spec, _ = source
    if kind == "parent":
        value = "../outside.mp4"
    elif kind == "absolute":
        value = str(tmp_path.parent / "outside.mp4")
    elif kind == "symlink":
        (tmp_path / "alias.mp4").symlink_to(tmp_path / spec["inputs"][0]["path"])
        value = "alias.mp4"
    else:
        value = "input"
    spec["inputs"] = [{"path": value}]
    with pytest.raises(MediaError):
        assemble(workspace, spec)
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize(
    "kind",
    ["same_output", "duplicate_source_id", "unknown_spec", "wrong_output_format"],
)
def test_ambiguous_specifications_are_refused(source, kind):
    workspace, spec, _ = source
    if kind == "same_output":
        spec["manifest"] = spec["video"]
    elif kind == "duplicate_source_id":
        for item in spec["inputs"]:
            item["id"] = "duplicate"
    elif kind == "unknown_spec":
        spec["unknown"] = "ignored?"
    else:
        spec["video"] = "output/video.txt"
    with pytest.raises(MediaError):
        assemble(workspace, spec)
    assert not (workspace.root / "output").exists()


def test_non_mp4_content_is_not_auto_detected_as_a_playlist(source):
    workspace, spec, _ = source
    path = workspace.root / "playlist.mp4"
    path.write_text("#EXTM3U\n#EXTINF:1\nfile:///unrelated/private.ts\n")
    spec["inputs"] = [{"path": path.name}]
    with pytest.raises(MediaError, match="MEDIA_COMMAND_FAILED"):
        assemble(workspace, spec)
    assert not (workspace.root / "output").exists()


def test_failed_second_publication_preserves_racing_file_and_rolls_back_first(
    tmp_path, monkeypatch
):
    workspace = Workspace(tmp_path)
    first = tmp_path / "staged-video"
    second = tmp_path / "staged-manifest"
    first.write_bytes(b"video")
    second.write_bytes(b"manifest")
    original = os.link

    def raced(source, target, **kwargs):
        if target == "manifest.json":
            descriptor = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                dir_fd=kwargs["dst_dir_fd"],
            )
            with os.fdopen(descriptor, "wb") as output:
                output.write(b"other writer")
        return original(source, target, **kwargs)

    monkeypatch.setattr(os, "link", raced)
    with pytest.raises(FileExistsError):
        workspace.publish({"video.mp4": first, "manifest.json": second}, [])
    assert (
        not (tmp_path / "video.mp4").exists()
        and (tmp_path / "manifest.json").read_bytes() == b"other writer"
    )
