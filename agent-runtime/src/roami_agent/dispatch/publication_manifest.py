"""Snapshot selected media from a current author's retained manifest, without publishing."""

import hashlib
import json
import mimetypes
import re
from pathlib import Path

from roami_agent.protocol.errors import DomainError
from roami_agent.storage.database import row
from roami_agent.storage.publication_author_scope import candidate_artifacts
from roami_agent.storage.task_deliverables import read_output


def selected_files(body, scope, paths):
    try:
        manifest = json.loads(body)
        identity = manifest["identity"]
        if any(identity[k] != scope[k] for k in ("taskId", "revision", "runId")):
            raise ValueError("identity")
        if (
            not isinstance(paths, list)
            or not 1 <= len(paths) <= 30
            or len(set(paths)) != len(paths)
        ):
            raise ValueError("selection")
        files = manifest["files"]
        if not isinstance(files, list) or len(files) > 1000:
            raise ValueError("files")
        by_path = {}
        for item in files:
            path = item["path"]
            if not isinstance(path, str) or path in by_path:
                raise ValueError("duplicate")
            by_path[path] = item
        result = []
        for path in paths:
            if path not in by_path:
                raise DomainError("PUBLICATION_CONTENT_USE_RELATIVE_MANIFEST_FILE_PATH", 409)
            item = by_path[path]
            relative = Path(path)
            if (
                relative.is_absolute()
                or not relative.parts
                or any(part.startswith(".") for part in relative.parts)
            ):
                raise ValueError("path")
            if any(item[k] != scope[k] for k in ("taskId", "revision", "runId")):
                raise ValueError("identity")
            if type(item["bytes"]) is not int or not 0 < item["bytes"] <= 128 * 1024 * 1024:
                raise ValueError("size")
            if not isinstance(item["sha256"], str) or not re.fullmatch(
                r"[0-9a-f]{64}", item["sha256"]
            ):
                raise ValueError("hash")
            result.append({k: item[k] for k in ("path", "bytes", "sha256")})
        return result
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise DomainError("INVALID_PUBLICATION_MANIFEST", 409) from exc


class PublicationManifest:
    def __init__(self, database, artifacts):
        self.db, self.artifacts = database, artifacts

    async def snapshot(self, binding, scope, manifest_reference, paths):
        await self.db.call(lambda db: candidate_artifacts(db, binding, scope, [manifest_reference]))
        metadata = await self.artifacts.get(binding["owner"], manifest_reference["id"])
        if not 0 < metadata["sizeBytes"] <= 2 * 1024 * 1024:
            raise DomainError("INVALID_PUBLICATION_MANIFEST", 409)
        reference, body = await self.artifacts.read(binding["owner"], manifest_reference["id"])
        if reference["sha256"] != manifest_reference["sha256"]:
            raise DomainError("PUBLICATION_MANIFEST_CHANGED", 409)
        entries = selected_files(body, scope, paths)
        retained = await self.db.call(
            lambda db: row(db, "SELECT metadata_json FROM artifacts WHERE id=?", (reference["id"],))
        )
        source = json.loads(retained["metadata_json"]).get("sourceFile")
        if not isinstance(source, str):
            raise DomainError("PUBLICATION_MANIFEST_SOURCE_REQUIRED", 409)
        preparation = await self.db.call(
            lambda db: row(
                db,
                "SELECT payload_json FROM events WHERE event_key=? AND task_id=?",
                ("workspace:" + scope["runId"], scope["taskId"]),
            )
        )
        workspace = (
            json.loads(preparation["payload_json"]).get("workspace", {}) if preparation else {}
        )
        root = workspace.get("directory")
        if not isinstance(root, str) or not Path(root).is_absolute():
            raise DomainError("PUBLICATION_MANIFEST_SOURCE_REQUIRED", 409)
        try:
            Path(source).relative_to(root)
        except ValueError as exc:
            raise DomainError("PUBLICATION_MANIFEST_SOURCE_REQUIRED", 409) from exc
        snapshots = []
        for entry in entries:
            previous = await self.db.call(
                lambda db, entry=entry: row(
                    db,
                    "SELECT a.id,a.sha256 FROM swarm_publication_source_files s JOIN artifacts a ON a.id=s.artifact_id WHERE s.manifest_artifact_id=? AND s.relative_path=? AND s.source_sha256=? AND s.source_size=?",
                    (reference["id"], entry["path"], entry["sha256"], entry["bytes"]),
                )
            )
            if previous:
                await self.db.call(
                    lambda db, previous=previous: candidate_artifacts(
                        db, binding, scope, [previous]
                    )
                )
                await self.artifacts.verified_path(binding["owner"], previous["id"])
                snapshots.append(
                    {
                        "path": entry["path"],
                        **await self.artifacts.get(binding["owner"], previous["id"]),
                    }
                )
                continue
            try:
                _, data = await self.artifacts._io(
                    read_output, root, str(Path(source).parent / entry["path"]), entry["bytes"]
                )
                if (
                    len(data) != entry["bytes"]
                    or hashlib.sha256(data).hexdigest() != entry["sha256"]
                ):
                    raise ValueError("changed")
            except (OSError, ValueError) as exc:
                raise DomainError("PUBLICATION_SOURCE_CHANGED", 409) from exc
            artifact = await self.artifacts.put(
                binding["owner"],
                data,
                task_id=scope["taskId"],
                name=Path(entry["path"]).name,
                mime_type=mimetypes.guess_type(entry["path"])[0] or "application/octet-stream",
                metadata={"kind": "deliverable", "runId": scope["runId"], "provisional": False},
            )

            def register(db, artifact=artifact, entry=entry):
                candidate_artifacts(db, binding, scope, [manifest_reference])
                db.execute(
                    "INSERT INTO swarm_publication_source_files(artifact_id,manifest_artifact_id,manifest_sha256,relative_path,source_sha256,source_size) VALUES(?,?,?,?,?,?) ON CONFLICT(manifest_artifact_id,relative_path) DO NOTHING",
                    (
                        artifact["id"],
                        reference["id"],
                        reference["sha256"],
                        entry["path"],
                        entry["sha256"],
                        entry["bytes"],
                    ),
                )
                return row(
                    db,
                    "SELECT artifact_id FROM swarm_publication_source_files WHERE manifest_artifact_id=? AND relative_path=? AND source_sha256=? AND source_size=?",
                    (reference["id"], entry["path"], entry["sha256"], entry["bytes"]),
                )

            registered = await self.db.call(register, write=True)
            if not registered:
                raise DomainError("PUBLICATION_SOURCE_CHANGED", 409)
            artifact = await self.artifacts.get(binding["owner"], registered["artifact_id"])
            await self.artifacts.verified_path(binding["owner"], artifact["id"])
            snapshots.append({"path": entry["path"], **artifact})
        return {
            "manifestArtifactId": reference["id"],
            "artifacts": snapshots,
            "publicationAuthorized": False,
        }
