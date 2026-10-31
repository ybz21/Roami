# /// script
# requires-python = ">=3.12"
# dependencies = ["lxml>=5,<7", "jsonschema>=4.23,<5"]
# ///
"""Standalone presentation Skill entry point; no Agent runtime imports or model calls."""

import argparse
import hashlib
import json
import sys
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree

from document_publication import PublicationError, Workspace
from jsonschema import Draft202012Validator, ValidationError
from lxml import etree
from office_palette import installed_presentation_palette
from pptx_edits import edit_presentation
from pptx_package import PresentationError, presentation_metadata


def inspect(workspace, path, slide=None):
    if Path(path).suffix.lower() != ".pptx":
        raise PublicationError("PPTX_REQUIRED")
    body = workspace.read(path)
    document = presentation_metadata(body)
    document["slideCount"] = len(document["slides"])
    if slide is not None:
        if type(slide) is not int or not 1 <= slide <= document["slideCount"]:
            raise PresentationError("PRESENTATION_TARGET_NOT_FOUND")
        document["slides"] = [
            item for item in document["slides"] if item["number"] == slide
        ]
    return {
        "path": str(workspace.relative(path)),
        "sha256": hashlib.sha256(body).hexdigest(),
        "sourceSizeBytes": len(body),
        "editorPalette": installed_presentation_palette(),
        **document,
    }


def edit(workspace, request):
    schema = json.loads(
        Path(__file__).with_name("edit-request.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(request)
    source, destination = request["path"], request["destination"]
    if any(Path(path).suffix.lower() != ".pptx" for path in [source, destination]):
        raise PublicationError("PPTX_REQUIRED")
    if workspace.relative(source) == workspace.relative(destination):
        raise PublicationError("OUTPUT_MUST_DIFFER")
    body = workspace.read(source)
    digest = hashlib.sha256(body).hexdigest()
    if digest != request["expectedSha256"]:
        raise PublicationError("SOURCE_CHANGED")
    edited, changes = edit_presentation(
        body, request["operations"], installed_presentation_palette()
    )
    expected = request["expectedDestinationSha256"]
    result = workspace.publish(
        source, digest, destination, None if expected == "null" else expected, edited
    )
    return {**result, "changes": changes}


def named_colors(
    workspace, path, destination, source_sha, slide, names, destination_sha=None
):
    observed = inspect(workspace, path)
    palette = observed["editorPalette"]
    if palette is None:
        raise PresentationError("PRESENTATION_PALETTE_UNAVAILABLE")
    selected = next(
        (item for item in observed["slides"] if item["number"] == slide), None
    )
    if selected is None:
        raise PresentationError("PRESENTATION_TARGET_NOT_FOUND")
    if len(names) != len(selected["textObjects"]):
        raise PresentationError("PRESENTATION_TARGET_COUNT_MISMATCH")
    return edit(
        workspace,
        {
            "path": path,
            "expectedSha256": source_sha,
            "destination": destination,
            "expectedDestinationSha256": destination_sha,
            "operations": [
                {
                    "slide": slide,
                    "target": {"order": "top_to_bottom", "ordinal": rank},
                    "color": {
                        "editor": palette["editor"],
                        "palette": palette["name"],
                        "name": name,
                    },
                }
                for rank, name in enumerate(names, 1)
            ],
        },
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["inspect", "edit", "colors"])
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--path", help="PPTX path for inspect")
    requests = parser.add_mutually_exclusive_group()
    requests.add_argument("--request", help="Workspace JSON request path for edit")
    requests.add_argument("--request-json", help="Inline JSON request for edit")
    parser.add_argument("--destination", help="Separate output PPTX for colors")
    parser.add_argument("--expected-sha256", help="Observed source hash for colors")
    parser.add_argument(
        "--expected-destination-sha256", help="Observed existing output hash"
    )
    parser.add_argument(
        "--slide", type=int, help="Slide number for inspect/colors (starts at 1)"
    )
    parser.add_argument(
        "--names", nargs="+", help="Installed palette names in top-to-bottom order"
    )
    args = parser.parse_args(argv)
    color_options = any(
        (
            args.destination,
            args.expected_sha256,
            args.expected_destination_sha256,
            args.names,
        )
    )
    if (
        (
            args.operation == "inspect"
            and (not args.path or args.request or args.request_json or color_options)
        )
        or (
            args.operation == "edit"
            and (
                not (args.request or args.request_json)
                or args.path
                or color_options
                or args.slide is not None
            )
        )
        or (
            args.operation == "colors"
            and (
                not all(
                    (
                        args.path,
                        args.destination,
                        args.expected_sha256,
                        args.slide,
                        args.names,
                    )
                )
                or args.request
                or args.request_json
            )
        )
    ):
        parser.error(
            "inspect needs --path; edit needs --request; colors needs source/output/hash/slide/names"
        )
    try:
        workspace = Workspace(args.workspace)
        if args.operation == "inspect":
            result = inspect(workspace, args.path, args.slide)
        elif args.operation == "colors":
            result = named_colors(
                workspace,
                args.path,
                args.destination,
                args.expected_sha256,
                args.slide,
                args.names,
                args.expected_destination_sha256,
            )
        else:
            result = edit(
                workspace,
                json.loads(
                    args.request_json
                    if args.request_json is not None
                    else workspace.read(args.request, maximum=1024 * 1024)
                ),
            )
        print(json.dumps({"ok": True, **result}, ensure_ascii=False))
        return 0
    except PublicationError as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(error),
                    "writePublished": None if error.published else False,
                }
            )
        )
        return 2 if error.published else 1
    except PresentationError as error:
        print(json.dumps({"ok": False, "error": str(error), "writePublished": False}))
        return 1
    except (
        ValidationError,
        ValueError,
        KeyError,
        IndexError,
        RuntimeError,
        OSError,
        zipfile.BadZipFile,
        ElementTree.ParseError,
        etree.XMLSyntaxError,
        zlib.error,
    ) as error:
        print(
            json.dumps(
                {"ok": False, "error": type(error).__name__, "writePublished": False}
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
