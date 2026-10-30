"""Expose presentation structure through the existing bound file read capability."""

import asyncio
import base64
import hashlib
import json
import zipfile
from pathlib import PurePath
from xml.etree import ElementTree

from roami_agent.documents.office_palettes import installed_presentation_palette
from roami_agent.documents.presentation import presentation_metadata
from roami_agent.protocol.errors import DomainError


class WorkspacePresentationReads:
    page_bytes = 16000

    def __init__(self, files, raw_read):
        self.files, self.raw_read = files, raw_read

    async def read(self, args, binding):
        if args.get("view", "raw") == "raw":
            return await self.raw_read(args, binding)
        if PurePath(args["path"]).suffix.lower() != ".pptx":
            raise DomainError("DOCUMENT_VIEW_UNSUPPORTED")
        source = await self.files.read({"path": args["path"], "limit": 1}, binding)
        body = await self.files.snapshot(args["path"], binding, maximum=64 * 1024 * 1024)
        if hashlib.sha256(body).hexdigest() != source["sha256"]:
            raise DomainError("FILE_CHANGED", 409)

        def inspect():
            try:
                document = presentation_metadata(body)
            except (ValueError, KeyError, RuntimeError, zipfile.BadZipFile, ElementTree.ParseError):
                raise DomainError("PRESENTATION_INVALID") from None
            return json.dumps(
                {"editorPalette": installed_presentation_palette(), **document},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()

        representation = await asyncio.to_thread(inspect)
        offset, limit = args.get("offset", 0), args.get("limit", self.page_bytes)
        page = representation[offset : offset + limit]
        try:
            data, encoding = page.decode(), "utf-8"
        except UnicodeDecodeError:
            data, encoding = base64.b64encode(page).decode(), "base64"
        return {
            "data": data,
            "encoding": encoding,
            "view": "document",
            "offsetBytes": offset,
            "readBytes": len(page),
            "sizeBytes": len(representation),
            "sourceSizeBytes": source["sizeBytes"],
            "sha256": source["sha256"],
            "viewSha256": hashlib.sha256(representation).hexdigest(),
            "nextOffset": offset + len(page) if offset + len(page) < len(representation) else None,
        }
