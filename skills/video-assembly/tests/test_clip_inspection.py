"""Check actual decoded content, timestamps and guarded inspection publication."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from clip_inspection import inspect_clip
from video_workspace import MediaError, Workspace, sha256


def encode(output, inputs, *options):
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            *inputs,
            *options,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(output),
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="session")
def media(tmp_path_factory):
    root = tmp_path_factory.mktemp("inspection-media")
    recipe = json.loads(
        (
            Path(__file__).parents[3] / "cases/case-104-mech-vi01/input/recipe.json"
        ).read_text()
    )
    colors = recipe["colors"]
    for i, color in enumerate(colors):
        Image.new("RGB", (96, 72), color).save(root / f"{i}.png")
    durations = recipe["variableDurations"]
    concat = root / "frames.txt"
    concat.write_text(
        "".join(
            f"file '{i}.png'\nduration {duration}\n"
            for i, duration in enumerate(durations)
        )
        + f"file '{len(colors) - 1}.png'\n"
    )
    encode(
        root / "variable.mp4",
        ["-f", "concat", "-safe", "0", "-i", str(concat)],
        "-vsync",
        "vfr",
    )
    encode(root / "fixed.mp4", ["-f", "lavfi", "-i", "color=red:s=80x60:r=2:d=2"])
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-itsoffset",
            "2",
            "-i",
            str(root / "fixed.mp4"),
            "-map",
            "0:v:0",
            "-c",
            "copy",
            "-copyts",
            str(root / "offset.mp4"),
        ],
        check=True,
        capture_output=True,
    )
    portrait = Image.new("RGB", (96, 192), "lime")
    portrait.paste(Image.new("RGB", (96, 48), "red"), (0, 0))
    portrait.paste(Image.new("RGB", (96, 48), "blue"), (0, 144))
    portrait.save(root / "portrait.png")
    encode(
        root / "portrait.mp4",
        ["-loop", "1", "-i", str(root / "portrait.png")],
        "-frames:v",
        "1",
    )
    encode(root / "single.mp4", ["-f", "lavfi", "-i", "color=red:s=80x60:r=2:d=0.5"])
    encode(
        root / "streams.mp4",
        [
            "-f",
            "lavfi",
            "-i",
            "color=red:s=80x60:r=2:d=1",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=160x120:r=2:d=1",
        ],
        "-map",
        "0:v",
        "-map",
        "1:v",
    )
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.5",
            "-c:a",
            "aac",
            str(root / "audio.mp4"),
        ],
        check=True,
        capture_output=True,
    )
    return root


@pytest.fixture
def source(tmp_path, media):
    path = tmp_path / "clip.mp4"
    path.write_bytes((media / "fixed.mp4").read_bytes())
    return Workspace(tmp_path), {
        "input": {"path": "clip.mp4", "sha256": sha256(path)},
        "image": "work/contact.png",
        "manifest": "work/contact.json",
    }


def replace_source(workspace, spec, path):
    target = workspace.root / spec["input"]["path"]
    target.write_bytes(path.read_bytes())
    spec["input"]["sha256"] = sha256(target)


def result(workspace, spec):
    receipt = inspect_clip(workspace, spec)
    manifest = json.loads((workspace.root / spec["manifest"]).read_text())
    assert all(
        sha256(workspace.root / x["path"]) == x["sha256"] for x in receipt["outputs"]
    )
    assert sha256(workspace.root / spec["input"]["path"]) == spec["input"]["sha256"]
    assert (
        not receipt["semanticSelectionConfirmed"]
        and not manifest["semanticSelectionConfirmed"]
    )
    return receipt, manifest


def test_actual_frame_time_does_not_claim_the_requested_time(source):
    workspace, spec = source
    spec["fractions"] = [0, 0.3, 1]
    _, manifest = result(workspace, spec)
    assert [x["frameIndex"] for x in manifest["samples"]] == [0, 1, 3]
    assert [x["seconds"] for x in manifest["samples"]] == [0, 0.5, 1.5]
    assert manifest["samples"][1]["requests"] == [{"fraction": 0.3, "seconds": 0.6}]
    with Image.open(workspace.root / spec["image"]) as sheet:
        assert sheet.getpixel((192, 136))[0] > 240


def test_single_frame_keeps_all_requests_without_duplicating_the_image(source, media):
    workspace, spec = source
    replace_source(workspace, spec, media / "single.mp4")
    receipt, manifest = result(workspace, spec)
    assert receipt["sampleCount"] == manifest["decodedFrameCount"] == 1
    assert len(manifest["samples"][0]["requests"]) == 5
    assert manifest["samples"][0]["seconds"] == 0


def test_variable_frame_rate_pairs_pixels_with_presentation_time(source, media):
    workspace, spec = source
    replace_source(workspace, spec, media / "variable.mp4")
    spec["fractions"] = [0, 0.05, 0.4, 0.9, 1]
    _, manifest = result(workspace, spec)
    assert [x["seconds"] for x in manifest["samples"]] == pytest.approx(
        [0, 0.04, 0.28, 0.6, 0.64]
    )
    assert [x["frameIndex"] for x in manifest["samples"]] == [0, 1, 2, 3, 4]
    assert manifest["timing"]["decodedEndSeconds"] == pytest.approx(0.68)
    assert manifest["samplingDurationSeconds"] >= 0.68
    with Image.open(workspace.root / spec["image"]) as sheet:
        pixels = [
            sheet.getpixel(((i % 3) * 384 + 192, (i // 3) * 244 + 136))
            for i in range(5)
        ]
    assert all(
        pixels[i][i] > 240 and sum(pixels[i][j] for j in range(3) if j != i) < 20
        for i in range(3)
    )
    assert all(p[0] > 240 and p[1] > 240 and p[2] < 10 for p in pixels[3:])


def test_nonzero_source_origin_is_preserved_but_offsets_are_relative(source, media):
    workspace, spec = source
    replace_source(workspace, spec, media / "offset.mp4")
    spec["fractions"] = [0, 0.5, 1]
    _, manifest = result(workspace, spec)
    assert manifest["sourceStartTimestamp"] == 2
    assert manifest["samplingDurationSeconds"] == 2
    assert [x["seconds"] for x in manifest["samples"]] == [0, 1, 1.5]
    assert [x["sourceTimestamp"] for x in manifest["samples"]] == [2, 3, 3.5]


def test_first_video_stream_matches_the_probed_timeline(source, media):
    workspace, spec = source
    replace_source(workspace, spec, media / "streams.mp4")
    _, manifest = result(workspace, spec)
    assert manifest["samples"][0]["width"] == 80
    with Image.open(workspace.root / spec["image"]) as sheet:
        r, _, b = sheet.getpixel((192, 136))
    assert r > 240 and b < 10


def test_portrait_preview_keeps_both_ends_of_the_supplied_frame(source, media):
    workspace, spec = source
    replace_source(workspace, spec, media / "portrait.mp4")
    _, manifest = result(workspace, spec)
    assert manifest["samples"][0]["width"] == 96
    assert manifest["samples"][0]["height"] == 192
    with Image.open(workspace.root / spec["image"]) as sheet:
        top = sheet.getpixel((192, 43))
        bottom = sheet.getpixel((192, 229))
    assert top[0] > 240 and top[2] < 10
    assert bottom[2] > 240 and bottom[0] < 10


def test_invalid_video_does_not_publish_or_modify_input(source):
    workspace, spec = source
    path = workspace.root / spec["input"]["path"]
    path.write_bytes(b"invalid mp4")
    spec["input"]["sha256"] = sha256(path)
    with pytest.raises(MediaError, match="MEDIA_COMMAND_FAILED"):
        inspect_clip(workspace, spec)
    assert path.read_bytes() == b"invalid mp4"
    assert not (workspace.root / "work").exists()


@pytest.mark.parametrize("key", ["image", "manifest"])
def test_existing_outputs_are_never_overwritten(source, key):
    workspace, spec = source
    path = workspace.root / spec[key]
    path.parent.mkdir()
    path.write_bytes(b"keep")
    with pytest.raises(MediaError, match="OUTPUT_EXISTS"):
        inspect_clip(workspace, spec)
    assert path.read_bytes() == b"keep"
    assert len(list(path.parent.iterdir())) == 1


def test_observed_source_hash_is_checked_before_decoding(source):
    workspace, spec = source
    spec["input"]["sha256"] = "0" * 64
    with pytest.raises(MediaError, match="SOURCE_CHANGED"):
        inspect_clip(workspace, spec)
    assert not (workspace.root / "work").exists()


@pytest.mark.parametrize("location", ["source", "output"])
def test_symlinks_do_not_cross_workspace_boundaries(source, tmp_path, location):
    workspace, spec = source
    if location == "source":
        alias = tmp_path / "alias.mp4"
        alias.symlink_to(tmp_path / "clip.mp4")
        spec["input"]["path"] = alias.name
    else:
        (tmp_path / "work").symlink_to(tmp_path.parent, target_is_directory=True)
    with pytest.raises(MediaError, match="SYMLINK_UNSUPPORTED"):
        inspect_clip(workspace, spec)


@pytest.mark.parametrize("fractions", [[], [True], [-0.1], [1.1], [float("nan")]])
def test_invalid_sample_requests_do_not_publish(source, fractions):
    workspace, spec = source
    spec["fractions"] = fractions
    with pytest.raises(MediaError, match="SAMPLE_FRACTIONS_INVALID"):
        inspect_clip(workspace, spec)
    assert not (workspace.root / "work").exists()


def test_audio_only_input_has_no_invented_video_samples(source, media):
    workspace, spec = source
    replace_source(workspace, spec, media / "audio.mp4")
    with pytest.raises(MediaError, match="VIDEO_TIMELINE_REQUIRED"):
        inspect_clip(workspace, spec)
    assert not (workspace.root / "work").exists()


def test_cli_emits_the_same_verifiable_saved_receipt(source):
    workspace, spec = source
    (workspace.root / "request.json").write_text(json.dumps(spec))
    command = [
        sys.executable,
        str(Path(__file__).parents[1] / "scripts/clip_inspection.py"),
        "--workspace",
        str(workspace.root),
        "--spec",
        "request.json",
    ]
    reply = json.loads(subprocess.check_output(command))
    assert reply["sampleCount"] == 4
    assert not reply["semanticSelectionConfirmed"]
    assert all(
        hashlib.sha256((workspace.root / x["path"]).read_bytes()).hexdigest()
        == x["sha256"]
        for x in reply["outputs"]
    )
