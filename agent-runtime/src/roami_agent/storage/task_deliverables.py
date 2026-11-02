"""Retain explicitly reported workspace outputs independently of tmux lifetime."""

import hashlib
import json
import mimetypes
import os
import re
import stat
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row, rows

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
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".sh",
    ".bash",
    ".css",
    ".scss",
    ".svg",
    ".sql",
}


def reported_paths(text, root=None, *, include_inline=True):
    if not isinstance(text, str):
        return []
    paths = re.findall(r"\[[^\]\n]*\]\(([^)\n]+)\)", text)
    if isinstance(root, str) and root:
        suffixes = "|".join(re.escape(suffix) for suffix in sorted(OUTPUT_SUFFIXES))
        paths += re.findall(
            re.escape(root.rstrip("/"))
            + r"/[^\r\n]*?(?:"
            + suffixes
            + r")(?=$|[\s\"'`<>()[\]{}*，。；：！？、（）]|\\[nr])",
            text,
        )
        if include_inline:
            paths += [
                quote(name, safe="/")
                for name in re.findall(r"(?<!`)`([^`\s]+)`(?!`)", text)
                if not Path(name).is_absolute()
                and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", name)
                and Path(name).suffix.lower() in OUTPUT_SUFFIXES
            ]
    return list(dict.fromkeys(paths))[:12]


def output_path(root, path):
    if path.startswith("/api/file/raw?"):
        path = parse_qs(urlsplit(path).query).get("path", [""])[0]
    elif path.startswith("/api/file/serve/"):
        path = "/" + unquote(path.removeprefix("/api/file/serve/")).lstrip("/")
    else:
        path = unquote(path)
    path = Path(path)
    if not path.is_absolute():
        path = Path(root) / path
    return path


def read_output(root, path, maximum, destination=None):
    root = Path(root).resolve(strict=True)
    path = output_path(root, path)
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
            if not stat.S_ISREG(info.st_mode) or (maximum and info.st_size > maximum):
                raise ValueError("invalid output")
            if destination is None:
                body = file.read(maximum + 1 if maximum else -1)
                if maximum and len(body) > maximum:
                    raise ValueError("large output")
                return str(path), body
            size = 0
            with open(destination, "xb") as output:
                while chunk := file.read(64 * 1024):
                    size += len(chunk)
                    if maximum and size > maximum:
                        raise ValueError("large output")
                    output.write(chunk)
            after = os.fstat(file.fileno())
            if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ) or size != info.st_size:
                raise ValueError("changed output")
            return str(path), size
    finally:
        os.close(descriptor)


def output_digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


class TaskDeliverables:
    def __init__(self, artifacts):
        self.artifacts = artifacts

    async def completion_file_updates(self, owner, task, attempt):
        receipts = await self.artifacts.db.call(
            lambda db: rows(
                db,
                "SELECT x.id,x.turn_id,native_content(x.arguments_json) AS arguments_json,"
                "json_extract(native_content(m.content_json),'$.text') AS result_text "
                "FROM tasks t JOIN turns u ON u.conversation_id=t.origin_conversation_id "
                "AND u.branch_id=t.origin_branch_id AND u.trigger_kind='completion' "
                "JOIN jobs j ON j.aggregate_id=u.id AND j.kind='turn.run' "
                "JOIN tool_calls x ON x.turn_id=u.id JOIN messages m ON m.id=x.result_message_id "
                "WHERE t.id=? AND t.owner_id=? AND json_extract(j.payload_json,'$.completion.taskId')=t.id "
                "AND json_extract(j.payload_json,'$.completion.runId')=? "
                "AND json_extract(j.payload_json,'$.completion.taskRevision')=t.revision "
                "AND x.tool_name IN ('file_write','file_patch') AND x.state='succeeded' "
                "ORDER BY x.created_ms DESC,x.rowid DESC",
                (task["id"], owner, attempt["id"]),
            )
        )
        updates = {}
        for receipt in receipts:
            args = json.loads(receipt["arguments_json"])
            result = json.loads(receipt["result_text"] or "{}")
            path = args.get("path") if isinstance(args, dict) else None
            digest = result.get("sha256") if isinstance(result, dict) else None
            if (
                isinstance(path, str)
                and Path(path).is_absolute()
                and isinstance(digest, str)
                and re.fullmatch(r"[a-f0-9]{64}", digest)
            ):
                updates.setdefault(
                    str(Path(path)),
                    {"sha256": digest, "toolCallId": receipt["id"], "turnId": receipt["turn_id"]},
                )
        return updates

    async def collect(self, owner, detail):
        task = detail["task"]
        stored = await self.artifacts.list(owner, task_id=task["id"], limit=100)
        references, unavailable = [], []
        remaining = self.artifacts.max_bytes or None
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
            progress = attempt.get("progress") or {}
            if not attempt.get("finishedMs") and progress.get("source") != "provider_transcript":
                continue
            updates = await self.completion_file_updates(owner, task, attempt)
            sources = reported_paths(result.get("summary", ""), root) + reported_paths(
                result.get("output", ""), root
            )
            declared = set(
                reported_paths(result.get("summary", ""), root, include_inline=False)
                + reported_paths(result.get("output", ""), root, include_inline=False)
            )
            reported_aliases = {}
            if progress.get("source") == "provider_transcript" and (
                not attempt.get("finishedMs") or result.get("summary") == progress.get("summary")
            ):
                declared.update(
                    reported_paths(
                        progress.get("summary", ""), progress.get("directory"), include_inline=False
                    )
                )
                for source in reported_paths(
                    progress.get("summary", ""), progress.get("directory")
                ):
                    original = source
                    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", source):
                        source = str(output_path(progress["directory"], source))
                        reported_aliases.setdefault(source, []).append(original)
                    sources.append(source)
            reported = set(sources)
            observed = await self.artifacts.db.call(
                lambda db, attempt=attempt: rows(
                    db,
                    "SELECT DISTINCT x.tool_name,json_extract(native_content(x.arguments_json),'$.path') AS path "
                    "FROM tool_calls x JOIN turns u ON u.id=x.turn_id "
                    "JOIN task_attempts a ON a.native_branch_id=u.branch_id "
                    "JOIN tasks t ON t.id=a.task_id "
                    "WHERE a.id=? AND t.id=? AND t.owner_id=? AND x.state='succeeded' "
                    "AND (x.tool_name='file_read' OR (x.tool_name='file_write' "
                    "AND json_type(native_content(x.arguments_json),'$.expectedSha256')='null')) LIMIT 24",
                    (attempt["id"], task["id"], owner),
                )
            )
            sources += [
                item["path"]
                for item in observed
                if isinstance(item["path"], str)
                and (item["tool_name"] == "file_write" or item["path"] in result.get("summary", ""))
            ]
            weak_names = {
                name
                for name in sources
                if name not in declared and len(Path(unquote(name)).parts) == 1
            }
            observed_files = {
                str(output_path(root, item["path"]))
                for item in observed
                if isinstance(root, str) and root and isinstance(item["path"], str)
            }
            for source in dict.fromkeys(sources):
                if (
                    any(item["downloadUrl"] == source for item in stored)
                    or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", source)
                    or source.startswith("#")
                ):
                    continue
                canonical = (
                    str(output_path(root, source)) if isinstance(root, str) and root else source
                )
                metadata = {
                    "runId": attempt["id"],
                    "sourcePath": source,
                    "sourceFile": canonical,
                    "kind": "deliverable",
                    "provisional": not bool(attempt.get("finishedMs")),
                }
                if canonical in reported_aliases:
                    metadata["reportedAliases"] = list(dict.fromkeys(reported_aliases[canonical]))
                update = updates.get(canonical)
                if update:
                    metadata["sourceUpdate"] = update

                def same_source(metadata, run_id=attempt["id"], root=root, canonical=canonical):
                    return (
                        metadata.get("runId") == run_id
                        and isinstance(metadata.get("sourcePath"), str)
                        and isinstance(root, str)
                        and (
                            metadata.get("sourceFile")
                            or str(output_path(root, metadata["sourcePath"]))
                        )
                        == canonical
                    )

                existing = next(
                    (
                        a
                        for a in stored
                        if same_source(a.get("metadata", {}))
                        and not (
                            a.get("metadata", {}).get("provisional") and attempt.get("finishedMs")
                        )
                        and (not update or a["sha256"] == update["sha256"])
                    ),
                    None,
                )
                if existing:
                    if existing not in references:
                        references.append(existing)
                    continue
                # Reaching the best-effort collection limit is not evidence of a missing side file.
                if len(references) >= 12 and source not in reported:
                    continue
                try:
                    if not isinstance(root, str) or not root:
                        raise ValueError("workspace binding missing")
                    deleted = await self.artifacts.db.call(
                        lambda db, attempt=attempt: rows(
                            db,
                            "SELECT metadata_json FROM artifacts WHERE owner_id=? AND task_id=? AND deleted_ms IS NOT NULL "
                            "AND json_extract(metadata_json,'$.runId')=?",
                            (owner, task["id"], attempt["id"]),
                        )
                    )
                    if (
                        any(same_source(json.loads(item["metadata_json"])) for item in deleted)
                        or remaining is not None
                        and remaining <= 0
                        or len(references) >= 12
                    ):
                        raise ValueError("output unavailable")
                    with tempfile.TemporaryDirectory(
                        prefix=".deliverable-", dir=self.artifacts.data_root
                    ) as directory:
                        staged = Path(directory) / "output"
                        path, size = await self.artifacts._io(
                            read_output, root, source, remaining, staged
                        )
                        if (
                            update
                            and await self.artifacts._io(output_digest, staged) != update["sha256"]
                        ):
                            raise ValueError("source changed after completion edit")
                        reference = await self.artifacts.put_file(
                            owner,
                            staged,
                            task_id=task["id"],
                            name=Path(path).name,
                            mime_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
                            metadata=metadata,
                        )
                    stored.append(reference)
                    references.append(reference)
                    if remaining is not None:
                        remaining -= size
                except (OSError, ValueError, DomainError) as error:
                    # A bare inline filename can describe an input, rather than declare an output.
                    if (
                        isinstance(error, FileNotFoundError)
                        and source in weak_names
                        and canonical not in observed_files
                        and error.filename == unquote(source)
                    ):
                        continue
                    unavailable.append(
                        {"sourcePath": source, "runId": attempt["id"], "state": "unavailable"}
                    )
        return {"artifacts": references, "unavailable": unavailable}
