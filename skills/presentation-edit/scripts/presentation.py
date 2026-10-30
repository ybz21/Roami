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


def inspect(workspace, path):
    if Path(path).suffix.lower() != ".pptx":
        raise PublicationError("PPTX_REQUIRED")
    body = workspace.read(path)
    return {
        "path": str(workspace.relative(path)),
        "sha256": hashlib.sha256(body).hexdigest(),
        "sourceSizeBytes": len(body),
        "editorPalette": installed_presentation_palette(),
        **presentation_metadata(body),
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["inspect", "edit"])
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--path", help="PPTX path for inspect")
    requests = parser.add_mutually_exclusive_group()
    requests.add_argument("--request", help="Workspace JSON request path for edit")
    requests.add_argument("--request-json", help="Inline JSON request for edit")
    args = parser.parse_args(argv)
    if (
        args.operation == "inspect"
        and (not args.path or args.request or args.request_json)
    ) or (
        args.operation == "edit"
        and (not (args.request or args.request_json) or args.path)
    ):
        parser.error("inspect needs --path; edit needs --request")
    try:
        workspace = Workspace(args.workspace)
        result = (
            inspect(workspace, args.path)
            if args.operation == "inspect"
            else edit(
                workspace,
                json.loads(
                    args.request_json
                    if args.request_json is not None
                    else workspace.read(args.request, maximum=1024 * 1024)
                ),
            )
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
