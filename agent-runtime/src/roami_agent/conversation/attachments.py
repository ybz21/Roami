"""User uploads are private evidence, bound atomically when a message is admitted."""

import asyncio
import hashlib
import io
import json
import os
import sys
from contextlib import suppress
from pathlib import Path, PurePath

from PIL import Image

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms
from roami_agent.protocol.image_limits import MAX_PIXELS
from roami_agent.storage.database import row

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS = 6
PREVIEW_BYTES = 2000


def attachment_rows(db, owner, ids):
    result = []
    for aid in ids:
        item = row(
            db,
            "SELECT * FROM artifacts WHERE id=? AND owner_id=? AND deleted_ms IS NULL",
            (aid, owner),
        )
        if not item or json.loads(item["metadata_json"]).get("source") != "chat-upload":
            raise DomainError("ATTACHMENT_NOT_FOUND", 404)
        result.append(item)
    return result


def context_attachments(db, owner, content):
    previews, evidence = [], []
    for reference in content.get("attachments", []):
        item = row(
            db,
            "SELECT * FROM artifacts WHERE id=? AND owner_id=? AND deleted_ms IS NULL AND NOT EXISTS(SELECT 1 FROM memory_tombstones t WHERE t.owner_id=artifacts.owner_id AND t.source_fingerprint=artifacts.sha256)",
            (reference["id"], owner),
        )
        if not item:
            previews.append({"name": reference["name"], "state": "unavailable"})
            continue
        metadata = json.loads(item["metadata_json"])
        previews.append(
            {
                "id": item["id"],
                "name": item["name"],
                "mimeType": item["mime_type"],
                **metadata.get("preview", {}),
            }
        )
        evidence.append({"artifactId": item["id"], "sha256": item["sha256"]})
    return previews, evidence


class Attachments:
    def __init__(self, database, artifacts):
        self.db, self.artifacts = database, artifacts
        self.uploads = asyncio.Lock()

    @staticmethod
    def preview(body, name):
        if body.startswith(b"%PDF-"):
            from pypdf import PdfReader
            from pypdf.errors import PyPdfError

            try:
                reader = PdfReader(io.BytesIO(body), strict=True)
                if reader.is_encrypted:
                    return "application/pdf", {"state": "encrypted"}
                text = ""
                for page in reader.pages[:10]:
                    contents = page.get_contents()
                    if contents and len(contents.get_data()) > 2 * 1024 * 1024:
                        return "application/pdf", {"state": "unavailable"}
                    text += (page.extract_text() or "") + "\n"
                    if len(text.encode()) > PREVIEW_BYTES:
                        break
                return "application/pdf", {
                    "state": "text" if text.strip() else "no_text",
                    "text": text.encode()[:PREVIEW_BYTES].decode(errors="ignore"),
                    "truncated": len(text.encode()) > PREVIEW_BYTES or len(reader.pages) > 10,
                }
            except (PyPdfError, ValueError, OSError, MemoryError, RecursionError):
                return "application/pdf", {"state": "unavailable"}
        if body.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")) or (
            body.startswith(b"RIFF") and body[8:12] == b"WEBP"
        ):
            try:
                with Image.open(io.BytesIO(body)) as image:
                    if (
                        image.format not in {"PNG", "JPEG", "WEBP"}
                        or image.width * image.height > MAX_PIXELS
                    ):
                        raise ValueError
                    mime = Image.MIME[image.format]
                    image.verify()
                return mime, {"state": "image"}
            except (OSError, ValueError, Image.DecompressionBombError):
                raise DomainError("ATTACHMENT_IMAGE_INVALID") from None
        try:
            text = body.decode("utf-8-sig")
            if "\x00" in text:
                raise ValueError
            return "text/plain", {
                "state": "text",
                "text": text.encode()[:PREVIEW_BYTES].decode(errors="ignore"),
                "truncated": len(text.encode()) > PREVIEW_BYTES,
            }
        except (UnicodeError, ValueError):
            return "application/octet-stream", {
                "state": "unsupported",
                "extension": PurePath(name).suffix[:20],
            }

    async def upload(self, owner, name, key, body):
        if (
            not key
            or len(key) > 200
            or not name
            or len(name) > 180
            or any(ord(c) < 32 or c in "/\\" for c in name)
            or name in {".", ".."}
        ):
            raise DomainError("INVALID_ATTACHMENT")
        if len(body) > min(MAX_UPLOAD_BYTES, self.artifacts.max_bytes):
            raise DomainError("ATTACHMENT_SIZE_LIMIT", 413)
        async with self.uploads:
            old = await self.db.call(
                lambda db: row(
                    db,
                    "SELECT * FROM artifacts WHERE owner_id=? AND json_extract(metadata_json,'$.source')='chat-upload' AND json_extract(metadata_json,'$.uploadKey')=? ORDER BY rowid LIMIT 1",
                    (owner, key),
                )
            )
            if old:
                if old["deleted_ms"] is not None:
                    raise DomainError("ATTACHMENT_NOT_FOUND", 404)
                if old["name"] != name or old["sha256"] != hashlib.sha256(body).hexdigest():
                    raise DomainError("REQUEST_KEY_CONFLICT", 409)
                return self.artifacts.reference(old)
            if body.startswith(b"%PDF-"):
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "roami_agent.conversation.attachment_preview",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    env={
                        "PATH": os.environ.get("PATH", ""),
                        "PYTHONPATH": str(Path(__file__).parents[2]),
                    },
                )
                try:
                    output, _ = await asyncio.wait_for(process.communicate(body), 6)
                    preview = (
                        json.loads(output) if process.returncode == 0 else {"state": "unavailable"}
                    )
                except TimeoutError:
                    with suppress(ProcessLookupError):
                        process.kill()
                    await process.wait()
                    preview = {"state": "unavailable"}
                except asyncio.CancelledError:
                    with suppress(ProcessLookupError):
                        process.kill()
                    await process.wait()
                    raise
                mime = "application/pdf"
            else:
                mime, preview = await asyncio.to_thread(self.preview, body, name)
            return await self.artifacts.put(
                owner,
                body,
                mime_type=mime,
                name=name,
                metadata={"source": "chat-upload", "uploadKey": key, "preview": preview},
            )

    @staticmethod
    def bind(db, owner, mid, ids):
        references = []
        for item in attachment_rows(db, owner, ids):
            if item["message_id"] not in {None, mid}:
                raise DomainError("ATTACHMENT_ALREADY_SENT", 409)
            db.execute("UPDATE artifacts SET message_id=? WHERE id=?", (mid, item["id"]))
            references.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "mimeType": item["mime_type"],
                    "sizeBytes": item["size_bytes"],
                    "previewState": json.loads(item["metadata_json"])["preview"]["state"],
                }
            )
        return references

    async def remove_draft(self, owner, aid):
        def write(db):
            item = row(
                db,
                "SELECT * FROM artifacts WHERE id=? AND owner_id=? AND json_extract(metadata_json,'$.source')='chat-upload'",
                (aid, owner),
            )
            if not item:
                raise DomainError("ATTACHMENT_NOT_FOUND", 404)
            if item["message_id"]:
                raise DomainError("ATTACHMENT_ALREADY_SENT", 409)
            db.execute(
                "UPDATE artifacts SET deleted_ms=COALESCE(deleted_ms,?) WHERE id=?", (now_ms(), aid)
            )
            return {"id": aid, "deleted": True}

        async with self.artifacts.mutations:
            return await self.db.call(write, write=True)
