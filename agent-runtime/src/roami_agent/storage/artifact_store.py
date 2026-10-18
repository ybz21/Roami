"""Private content-addressed evidence with owner-scoped references and integrity checks."""

import asyncio
import hashlib
import json
import os
import re
import stat
import tempfile
from concurrent.futures import ThreadPoolExecutor

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import identity, now_ms
from roami_agent.storage.database import row, rows


class ArtifactStore:
    def __init__(self, database, *, max_bytes=64 * 1024 * 1024):
        if (
            not isinstance(max_bytes, int)
            or isinstance(max_bytes, bool)
            or not 1 <= max_bytes <= 512 * 1024 * 1024
        ):
            raise DomainError("INVALID_ARTIFACT_CONFIG")
        self.db = database
        self.data_root = database.data_root.resolve()
        self.max_bytes = max_bytes
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-artifacts")
        self.capacity = asyncio.Semaphore(4)
        self.pending = set()
        self.closed = False
        # Every store view must serialize publication with physical reclamation.
        if not hasattr(database, "_artifact_mutations"):
            database._artifact_mutations = asyncio.Lock()
        self.mutations = database._artifact_mutations

    async def _io(self, function, *args):
        await self.capacity.acquire()
        if self.closed:
            self.capacity.release()
            raise DomainError("ARTIFACT_STORE_CLOSED", 503)
        future = asyncio.get_running_loop().run_in_executor(self.pool, function, *args)
        self.pending.add(future)

        def finished(done):
            self.pending.discard(done)
            self.capacity.release()
            if not done.cancelled():
                done.exception()

        future.add_done_callback(finished)
        return await asyncio.shield(future)

    def _path(self, digest, *, create=False):
        if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
            raise DomainError("ARTIFACT_INDEX_INVALID", 503)
        directory = self.data_root
        for component in ["agent-artifacts", "blobs", digest[:2]]:
            directory = directory / component
            if create:
                try:
                    directory.mkdir(mode=0o700)
                except FileExistsError:
                    pass
                else:
                    self._sync_directory(directory.parent)
            info = directory.lstat()
            if not stat.S_ISDIR(info.st_mode):
                raise DomainError("ARTIFACT_PATH_INVALID", 503)
        return directory / (digest + ".blob")

    @staticmethod
    def _sync_directory(directory):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _read(self, digest, expected_size, include_body=True):
        path = self._path(digest)
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError as exc:
            raise DomainError("ARTIFACT_FILE_MISSING", 503) from exc
        with os.fdopen(descriptor, "rb") as file:
            info = os.fstat(file.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_size != expected_size
                or info.st_size > self.max_bytes
            ):
                raise DomainError("ARTIFACT_INTEGRITY_FAILED", 503)
            body, digestor, size = bytearray(), hashlib.sha256(), 0
            while chunk := file.read(64 * 1024):
                size += len(chunk)
                if include_body:
                    body.extend(chunk)
                digestor.update(chunk)
                if size > self.max_bytes:
                    raise DomainError("ARTIFACT_INTEGRITY_FAILED", 503)
            if size != expected_size or digestor.hexdigest() != digest:
                raise DomainError("ARTIFACT_INTEGRITY_FAILED", 503)
            return bytes(body) if include_body else path

    def _write(self, body):
        digest = hashlib.sha256(body).hexdigest()
        path = self._path(digest, create=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".artifact-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(body)
                file.flush()
                os.fchmod(file.fileno(), 0o400)
                os.fsync(file.fileno())
            try:
                os.link(temporary, path, follow_symlinks=False)
            except FileExistsError:
                self._read(digest, len(body), False)
            self._sync_directory(path.parent)
            return digest, str(path.relative_to(self.data_root))
        finally:
            os.unlink(temporary)

    @staticmethod
    def _scope(db, owner, task_id, message_id):
        task = None
        if task_id:
            task = row(db, "SELECT * FROM tasks WHERE id=? AND owner_id=?", (task_id, owner))
            if not task:
                raise DomainError("ARTIFACT_SCOPE_NOT_FOUND", 404)
        if message_id:
            message = row(
                db,
                "SELECT m.* FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE m.id=? AND c.owner_id=?",
                (message_id, owner),
            )
            if not message:
                raise DomainError("ARTIFACT_SCOPE_NOT_FOUND", 404)
            if (
                task
                and message["conversation_id"] != task["origin_conversation_id"]
                and not row(
                    db,
                    "SELECT id FROM task_attempts WHERE task_id=? AND native_branch_id=?",
                    (task_id, message["branch_id"]),
                )
            ):
                raise DomainError("ARTIFACT_SCOPE_CONFLICT", 409)

    @staticmethod
    def reference(item):
        return {
            "id": item["id"],
            "taskId": item["task_id"],
            "messageId": item["message_id"],
            "name": item["name"],
            "mimeType": item["mime_type"],
            "sha256": item["sha256"],
            "sizeBytes": item["size_bytes"],
            "metadata": json.loads(item["metadata_json"]),
            "createdMs": item["created_ms"],
            "downloadUrl": "/api/agent/artifacts/" + item["id"] + "/content",
        }

    async def put(
        self,
        owner,
        body,
        *,
        mime_type,
        name="artifact",
        task_id=None,
        message_id=None,
        metadata=None,
    ):
        if not isinstance(owner, str) or not 1 <= len(owner) <= 200:
            raise DomainError("INVALID_ARTIFACT_OWNER")
        if any(
            value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 200)
            for value in [task_id, message_id]
        ):
            raise DomainError("INVALID_ARTIFACT_SCOPE")
        if not isinstance(body, bytes) or len(body) > self.max_bytes:
            raise DomainError("ARTIFACT_SIZE_LIMIT", 413)
        if not isinstance(mime_type, str) or not re.fullmatch(
            r"[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+", mime_type
        ):
            raise DomainError("INVALID_ARTIFACT_MIME")
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 180
            or name in {".", ".."}
            or any(ord(char) < 32 or char in "/\\" for char in name)
        ):
            raise DomainError("INVALID_ARTIFACT_NAME")
        try:
            if metadata is not None and not isinstance(metadata, dict):
                raise ValueError
            packed = json.dumps(
                metadata or {},
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            )
            if len(packed.encode()) > 16000:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise DomainError("INVALID_ARTIFACT_METADATA") from exc
        await self.db.call(lambda db: self._scope(db, owner, task_id, message_id))
        async with self.mutations:
            try:
                digest, path = await self._io(self._write, body)
            except OSError as exc:
                raise DomainError("ARTIFACT_STORAGE_UNAVAILABLE", 503) from exc
            if self.closed:
                raise DomainError("ARTIFACT_STORE_CLOSED", 503)

            def register(db):
                self._scope(db, owner, task_id, message_id)
                existing = row(
                    db,
                    "SELECT * FROM artifacts WHERE owner_id=? AND task_id IS ? AND message_id IS ? AND sha256=? AND mime_type=? AND name=? AND metadata_json=? AND deleted_ms IS NULL",
                    (owner, task_id, message_id, digest, mime_type.lower(), name, packed),
                )
                if existing:
                    return self.reference(existing)
                aid = identity()
                db.execute(
                    "INSERT INTO artifacts(id,owner_id,task_id,message_id,path,mime_type,sha256,size_bytes,created_ms,name,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        aid,
                        owner,
                        task_id,
                        message_id,
                        path,
                        mime_type.lower(),
                        digest,
                        len(body),
                        now_ms(),
                        name,
                        packed,
                    ),
                )
                return self.reference(row(db, "SELECT * FROM artifacts WHERE id=?", (aid,)))

            return await self.db.call(register, write=True)

    async def _owned(self, owner, artifact_id):
        item = await self.db.call(
            lambda db: row(
                db,
                "SELECT * FROM artifacts WHERE id=? AND owner_id=? AND deleted_ms IS NULL",
                (artifact_id, owner),
            )
        )
        if not item:
            raise DomainError("ARTIFACT_NOT_FOUND", 404)
        return item

    async def get(self, owner, artifact_id):
        return self.reference(await self._owned(owner, artifact_id))

    async def read(self, owner, artifact_id):
        item = await self._owned(owner, artifact_id)
        self._validate_path(item)
        try:
            body = await self._io(self._read, item["sha256"], item["size_bytes"])
        except OSError as exc:
            raise DomainError("ARTIFACT_FILE_MISSING", 503) from exc
        return self.reference(item), body

    @staticmethod
    def _validate_path(item):
        expected = "agent-artifacts/blobs/" + item["sha256"][:2] + "/" + item["sha256"] + ".blob"
        if item["path"] != expected:
            raise DomainError("ARTIFACT_PATH_INVALID", 503)

    async def verified_path(self, owner, artifact_id):
        item = await self._owned(owner, artifact_id)
        self._validate_path(item)
        try:
            path = await self._io(self._read, item["sha256"], item["size_bytes"], False)
        except OSError as exc:
            raise DomainError("ARTIFACT_FILE_MISSING", 503) from exc
        return self.reference(item), path

    async def list(self, owner, *, task_id=None, message_id=None, limit=50):
        def read(db):
            self._scope(db, owner, task_id, message_id)
            items = rows(
                db,
                "SELECT * FROM artifacts WHERE owner_id=? AND deleted_ms IS NULL"
                + (" AND task_id=?" if task_id else "")
                + (" AND message_id=?" if message_id else "")
                + " ORDER BY created_ms DESC,id LIMIT ?",
                (owner,)
                + ((task_id,) if task_id else ())
                + ((message_id,) if message_id else ())
                + (min(max(limit, 1), 100),),
            )
            return [self.reference(item) for item in items]

        return await self.db.call(read)

    async def delete(self, owner, artifact_id):
        def write(db):
            item = row(
                db, "SELECT id FROM artifacts WHERE id=? AND owner_id=?", (artifact_id, owner)
            )
            if not item:
                raise DomainError("ARTIFACT_NOT_FOUND", 404)
            db.execute(
                "UPDATE artifacts SET deleted_ms=COALESCE(deleted_ms,?) WHERE id=?",
                (now_ms(), artifact_id),
            )
            affected = rows(
                db,
                "WITH RECURSIVE affected(id) AS ("
                "SELECT memory_id FROM memory_sources WHERE artifact_id=? "
                "UNION SELECT e.derived_id FROM memory_edges e JOIN affected a ON e.parent_id=a.id) "
                "SELECT r.id FROM memory_records r JOIN affected a ON a.id=r.id WHERE r.owner_id=? "
                "AND (r.state IN ('active','conflict') OR EXISTS(SELECT 1 FROM memory_embeddings e WHERE e.memory_id=r.id))",
                (artifact_id, owner),
            )
            for memory in affected:
                db.execute(
                    "UPDATE memory_records SET state='candidate',updated_ms=? WHERE id=? AND state IN ('active','conflict')",
                    (now_ms(), memory["id"]),
                )
                db.execute("DELETE FROM memory_embeddings WHERE memory_id=?", (memory["id"],))
            if affected:
                db.execute(
                    "UPDATE owner_versions SET memory_epoch=memory_epoch+1 WHERE owner_id=?",
                    (owner,),
                )
                db.execute(
                    "UPDATE context_snapshots SET state='invalid' WHERE branch_id IN "
                    "(SELECT b.id FROM branches b JOIN conversations c ON c.id=b.conversation_id WHERE c.owner_id=?)",
                    (owner,),
                )
            return {"id": artifact_id, "deleted": True}

        return await self.db.call(write, write=True)

    async def for_attempt(self, owner, task_id, run_id, *, limit=5):
        def read(db):
            self._scope(db, owner, task_id, None)
            items = rows(
                db,
                "SELECT a.* FROM artifacts a JOIN messages m ON m.id=a.message_id "
                "JOIN task_attempts t ON t.native_branch_id=m.branch_id "
                "WHERE a.owner_id=? AND a.task_id=? AND t.task_id=? AND t.id=? AND a.deleted_ms IS NULL "
                "ORDER BY a.created_ms DESC,a.id LIMIT ?",
                (owner, task_id, task_id, run_id, min(max(limit, 1), 20)),
            )
            return [self.reference(item) for item in items]

        return await self.db.call(read)

    async def close(self):
        if self.closed:
            return
        self.closed = True
        await asyncio.gather(
            *(asyncio.shield(future) for future in tuple(self.pending)), return_exceptions=True
        )
        self.pool.shutdown(wait=True)
