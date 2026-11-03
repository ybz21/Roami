# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2,<4", "matplotlib>=3.8,<4", "python-pptx>=1,<2"]
# ///
"""Build a descriptive report through ordinary offline execution, without model calls."""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from presentation_layout import build
from series_charts import charts
from series_facts import analyze, csv_header
from slide_rendering import digest, font_family, render


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["workspace", "path", "date", "price", "volume", "destination"]:
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--matrix", nargs="*", default=[])
    parser.add_argument("--price-unit", default="source price units")
    parser.add_argument("--volume-unit", default="source volume units")
    parser.add_argument("--short", type=int, default=50)
    parser.add_argument("--long", type=int, default=200)
    parser.add_argument("--sessions-per-year", dest="sessions", type=int, default=252)
    parser.add_argument("--title", default="Price, risk and trading activity")
    parser.add_argument("--font")
    parser.add_argument("--calendar-timezone", default="UTC")
    parser.add_argument(
        "--source-schema",
        help="Original CSV for a requested schema-preserving cleaned export",
    )
    args = parser.parse_args()
    claimed = False
    try:
        root = Path(args.workspace).resolve(strict=True)
        source = (root / args.path).resolve(strict=True)
        destination = root / args.destination
        parent = destination.parent.resolve(strict=True)
        if (
            not source.is_relative_to(root)
            or not parent.is_relative_to(root)
            or destination.exists()
            or destination.is_symlink()
        ):
            raise ValueError("WORKSPACE_OR_NEW_DESTINATION_REQUIRED")
        if args.short < 2 or args.long <= args.short or args.sessions <= 0:
            raise ValueError("INVALID_ANALYSIS_PARAMETERS")
        body = source.read_bytes()
        before = hashlib.sha256(body).hexdigest()
        schema_path = None
        schema_reference = None
        if args.source_schema:
            schema_path = (root / args.source_schema).resolve(strict=True)
            if not schema_path.is_relative_to(root):
                raise ValueError("SCHEMA_REFERENCE_OUTSIDE_WORKSPACE")
            schema_body = schema_path.read_bytes()
            expected, actual = csv_header(schema_body), csv_header(body)
            if expected != actual:
                raise ValueError(
                    "CLEANED_CSV_SCHEMA_CHANGED: "
                    + json.dumps({"expected": expected, "actual": actual})
                )
            schema_reference = {
                "path": str(schema_path.relative_to(root)),
                "sha256": hashlib.sha256(schema_body).hexdigest(),
                "columns": expected,
            }
        font = font_family(args.font)
        facts, series = analyze(body, args)
        facts.update(
            sourceSha256=before, sourcePath=str(source.relative_to(root)), font=font
        )
        if schema_reference:
            facts["sourceSchemaReference"] = schema_reference
        with tempfile.TemporaryDirectory(
            prefix=".market-report-", dir=parent
        ) as directory:
            stage = Path(directory)
            (stage / "charts").mkdir()
            images = charts(stage / "charts", facts, series, font)
            count = build(stage, facts, images, args, font)
            review = render(stage, count)
            (stage / "facts.json").write_text(
                json.dumps(facts, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
            )
            review.update(sourceSha256=before, font=font)
            (stage / "review-manifest.json").write_text(
                json.dumps(review, indent=2) + "\n"
            )
            if digest(source) != before:
                raise ValueError("SOURCE_CHANGED")
            if schema_path and digest(schema_path) != schema_reference["sha256"]:
                raise ValueError("SOURCE_SCHEMA_CHANGED")
            destination.mkdir(mode=0o700)
            claimed = True
            files = []
            for path in sorted(
                stage.rglob("*"),
                key=lambda p: (p.name == "review-manifest.json", len(p.parts), str(p)),
            ):
                relative = path.relative_to(stage)
                target = destination / relative
                if path.is_dir():
                    target.mkdir(mode=0o700)
                else:
                    os.link(path, target, follow_symlinks=False)
                    files.append(
                        {
                            "path": str(target.relative_to(root)),
                            "sha256": digest(target),
                        }
                    )
            result = {
                "ok": True,
                "writePublished": True,
                "sourceSha256": before,
                "deckSha256": review["deckSha256"],
                "slides": count,
                "deliverables": [
                    str((destination / name).relative_to(root))
                    for name in ["report.pptx", "presenter-notes.md"]
                ],
                "reviewManifest": str(
                    (destination / "review-manifest.json").relative_to(root)
                ),
                "renderedPages": [
                    str((destination / page["path"]).relative_to(root))
                    for page in review["pages"]
                ],
                "visualInspectionPerformed": False,
                "files": files,
            }
            print(json.dumps(result, ensure_ascii=False))
    except (
        ValueError,
        OSError,
        subprocess.SubprocessError,
        KeyError,
        TypeError,
    ) as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(error),
                    "writePublished": None if claimed else False,
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
