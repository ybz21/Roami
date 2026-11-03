"""Publish input-only frame sequences and an auditable sampling manifest."""

import argparse
import json
import math
import tempfile
from pathlib import Path

from frame_samples import samples
from PIL import Image, ImageDraw, ImageFont, ImageOps
from video_workspace import MediaError, Workspace, sha256


def inspect_clip(workspace, spec):
    if not isinstance(spec, dict) or set(spec) - {
        "input",
        "image",
        "manifest",
        "fractions",
    }:
        raise MediaError("SPEC_INVALID")
    source = spec.get("input")
    if (
        not isinstance(source, dict)
        or set(source) - {"path", "sha256"}
        or not isinstance(source.get("path"), str)
        or not source["path"]
    ):
        raise MediaError("INPUT_INVALID")
    if not all(isinstance(spec.get(k), str) and spec[k] for k in ["image", "manifest"]):
        raise MediaError("OUTPUT_PATHS_REQUIRED")
    paths = [workspace.path(spec[k], exists=False) for k in ["image", "manifest"]]
    if len(set(paths)) != 2:
        raise MediaError("OUTPUT_PATHS_DUPLICATE")
    if any(path.exists() for path in paths):
        raise MediaError("OUTPUT_EXISTS")
    if paths[0].suffix.lower() != ".png" or paths[1].suffix.lower() != ".json":
        raise MediaError("OUTPUT_FORMAT_INVALID")
    fractions = spec.get("fractions", [0, 0.25, 0.5, 0.75, 1])
    if (
        not isinstance(fractions, list)
        or not fractions
        or any(type(x) not in (int, float) or not 0 <= x <= 1 for x in fractions)
    ):
        raise MediaError("SAMPLE_FRACTIONS_INVALID")
    with tempfile.TemporaryDirectory(
        prefix=".video-inspection-", dir=workspace.root
    ) as tmp:
        temp = Path(tmp)
        snapshot = temp / "input.mp4"
        retained = workspace.snapshot(source["path"], snapshot, source.get("sha256"))
        duration, start, count, selected, timing = samples(snapshot, fractions)
        columns = min(3, len(selected))
        cell_width, image_height, label_height = 384, 216, 28
        cell_height = image_height + label_height
        sheet = Image.new(
            "RGB",
            (columns * cell_width, math.ceil(len(selected) / columns) * cell_height),
            "white",
        )
        draw = ImageDraw.Draw(sheet)
        font = ImageFont.load_default(size=16)
        evidence = []
        for i, (picture, data) in enumerate(selected):
            x, y = (i % columns) * cell_width, (i // columns) * cell_height
            draw.text(
                (x + 4, y + 4),
                f"Frame {data['frameIndex']} at {data['seconds']:.3f} s",
                fill="black",
                font=font,
            )
            image = ImageOps.contain(picture, (cell_width, image_height))
            sheet.paste(
                image,
                (
                    x + (cell_width - image.width) // 2,
                    y + label_height + (image_height - image.height) // 2,
                ),
            )
            evidence.append(
                {**data, "sheetCell": {"row": i // columns, "column": i % columns}}
            )
        staged_image = temp / "sequence.png"
        sheet.save(staged_image)
        manifest = {
            "schemaVersion": 1,
            "input": retained,
            "samplingDurationSeconds": duration,
            "timing": timing,
            "sourceStartTimestamp": start,
            "decodedFrameCount": count,
            "requestedFractions": fractions,
            "samples": evidence,
            "contactSheet": {
                "path": str(paths[0].relative_to(workspace.root)),
                "sha256": sha256(staged_image),
                "width": sheet.width,
                "height": sheet.height,
                "columns": columns,
            },
            "semanticSelectionConfirmed": False,
        }
        staged_manifest = temp / "sequence.json"
        staged_manifest.write_text(json.dumps(manifest, indent=2) + "\n")
        workspace.publish(
            {spec["image"]: staged_image, spec["manifest"]: staged_manifest}, [retained]
        )
        return {
            "input": retained,
            "outputs": [
                {
                    "path": str(path.relative_to(workspace.root)),
                    "sha256": sha256(path),
                    "bytes": path.stat().st_size,
                }
                for path in paths
            ],
            "decodedFrameCount": count,
            "sampleCount": len(evidence),
            "semanticSelectionConfirmed": False,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--spec", required=True)
    args = parser.parse_args()
    workspace = Workspace(args.workspace)
    spec = json.loads(workspace.path(args.spec).read_text())
    print(json.dumps(inspect_clip(workspace, spec)))


if __name__ == "__main__":
    main()
