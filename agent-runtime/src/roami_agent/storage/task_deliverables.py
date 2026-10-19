"""Retain explicitly reported workspace outputs independently of tmux lifetime."""

import json
import mimetypes
import os
import re
import stat
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row

OUTPUT_SUFFIXES = {
    ".md",
    ".txt",
    ".csv",
    ".json",
    ".html",
    ".pdf",
    ".pptx",
    ".docx",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".mp4",
    ".webm",
    ".wav",
    ".mp3",
}


def reported_paths(text):
    if not isinstance(text, str):
        return []
    return list(dict.fromkeys(re.findall(r"\[[^\]\n]*\]\(([^)\n]+)\)", text)))[:12]


def read_output(root, path, maximum):
    root = Path(root).resolve(strict=True)
    if path.startswith("/api/file/raw?"):
        path = parse_qs(urlsplit(path).query).get("path", [""])[0]
    elif path.startswith("/api/file/serve/"):
        path = unquote(path.removeprefix("/api/file/serve"))
    else:
        path = unquote(path)
    path = Path(path)
    if not path.is_absolute():
        path = root / path
    relative = path.relative_to(root)
    if not relative.parts or any(p.startswith(".") for p in relative.parts):
        raise ValueError("unsafe path")
    if path.suffix.lower() not in OUTPUT_SUFFIXES:
        raise ValueError("unsupported output")
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        child = os.open(
            relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor
        )
        with os.fdopen(child, "rb") as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
                raise ValueError("invalid output")
            body = file.read(maximum + 1)
            if len(body) > maximum:
                raise ValueError("large output")
        return str(path), body
    finally:
        os.close(descriptor)


class TaskDeliverables:
    def __init__(self, artifacts):
        self.artifacts = artifacts

    async def collect(self, owner, detail):
        task = detail["task"]
        stored = await self.artifacts.list(owner, task_id=task["id"], limit=100)
        references, unavailable = [], []
        remaining = self.artifacts.max_bytes
        for attempt in detail["attempts"]:
            result = attempt.get("result") or {}
            preparation = await self.artifacts.db.call(
                lambda db, attempt=attempt: row(
                    db,
                    "SELECT payload_json FROM events WHERE event_key=? AND task_id=?",
                    ("workspace:" + attempt["id"], task["id"]),
                )
            )
            workspace = (
                json.loads(preparation["payload_json"]).get("workspace", {}) if preparation else {}
            )
            root = workspace.get("directory")
            if not attempt.get("finishedMs"):
                continue
            sources = reported_paths(result.get("summary", "")) + reported_paths(
                result.get("output", "")
            )
            for source in dict.fromkeys(sources):
                if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", source) or source.startswith("#"):
                    continue
                metadata = {"runId": attempt["id"], "sourcePath": source, "kind": "deliverable"}
                existing = next((a for a in stored if a.get("metadata") == metadata), None)
                if existing:
                    references.append(existing)
                    continue
                try:
                    if not isinstance(root, str) or not root:
                        raise ValueError("workspace binding missing")
                    deleted = await self.artifacts.db.call(
                        lambda db, attempt=attempt, source=source: row(
                            db,
                            "SELECT id FROM artifacts WHERE owner_id=? AND task_id=? AND deleted_ms IS NOT NULL "
                            "AND json_extract(metadata_json,'$.runId')=? AND json_extract(metadata_json,'$.sourcePath')=? LIMIT 1",
                            (owner, task["id"], attempt["id"], source),
                        )
                    )
                    if deleted or remaining <= 0 or len(references) >= 12:
                        raise ValueError("output unavailable")
                    path, body = await self.artifacts._io(read_output, root, source, remaining)
                    reference = await self.artifacts.put(
                        owner,
                        body,
                        task_id=task["id"],
                        name=Path(path).name,
                        mime_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
                        metadata=metadata,
                    )
                    stored.append(reference)
                    references.append(reference)
                    remaining -= len(body)
                except (OSError, ValueError, DomainError):
                    unavailable.append(
                        {"sourcePath": source, "runId": attempt["id"], "state": "unavailable"}
                    )
        return {"artifacts": references, "unavailable": unavailable}
