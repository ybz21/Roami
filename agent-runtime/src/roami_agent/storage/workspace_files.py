"""Workspace file I/O with source hashes and durable atomic publication."""

import asyncio
import base64
import hashlib
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from roami_agent.protocol.errors import DomainError, ToolCancellation
from roami_agent.protocol.identity import identity
from roami_agent.storage.database import row
from roami_agent.storage.file_lines import read_line_page

CURRENT_CONTENT = object()


class WorkspaceFiles:
    def __init__(self, settings, database=None):
        self.settings, self.db = settings, database
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-files")
        self.capacity = asyncio.Semaphore(4)
        self.pending = set()
        self.closed = False
        self.observed = {}

    async def _io(self, operation, *args):
        try:
            await self.capacity.acquire()
        except asyncio.CancelledError:
            raise ToolCancellation(input_stopped=True) from None
        if self.closed:
            self.capacity.release()
            raise DomainError("FILE_STORE_CLOSED", 503)
        future = asyncio.get_running_loop().run_in_executor(self.pool, operation, *args)
        self.pending.add(future)

        def finished(done):
            self.pending.discard(done)
            self.capacity.release()
            if not done.cancelled():
                done.exception()

        future.add_done_callback(finished)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            if not future.done():
                try:
                    await asyncio.wait({future}, timeout=2)
                except asyncio.CancelledError:
                    pass
            raise ToolCancellation(input_stopped=future.done()) from None

    def location(self, path, binding):
        workspace = binding.get("workspace")
        if binding.get("taskId") and not workspace:
            raise DomainError("TASK_WORKSPACE_REQUIRED")
        if not isinstance(path, str) or not path or "\0" in path:
            raise DomainError("INVALID_FILE_PATH")
        roots = [Path(workspace["directory"]).resolve()] if workspace else self.settings.shell_roots
        requested = Path(path).expanduser()
        if not requested.is_absolute():
            if not workspace:
                raise DomainError("WORKSPACE_REQUIRED")
            requested = Path(workspace["directory"]) / requested
        requested = Path(os.path.normpath(requested))
        for root in roots:
            root = Path(root).resolve()
            if root in requested.parents:
                return root, requested.relative_to(root).parts
        raise DomainError("WORKSPACE_OUTSIDE_CONFIGURED_ROOTS")

    @staticmethod
    def _parent(location):
        root, components = location
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in components[:-1]:
                child = os.open(
                    component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                )
                os.close(descriptor)
                descriptor = child
            return descriptor, components[-1]
        except BaseException:
            os.close(descriptor)
            raise

    def _read(self, parent, name, maximum=None):
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise DomainError("FILE_TYPE_OR_SIZE_UNSUPPORTED")
            if maximum is not None and info.st_size > maximum:
                raise DomainError("FILE_TYPE_OR_SIZE_UNSUPPORTED")
            body = file.read() if maximum is None else file.read(maximum + 1)
            after = os.fstat(file.fileno())
            if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise DomainError("FILE_CHANGED", 409)
            if len(body) != info.st_size:
                raise DomainError("FILE_CHANGED", 409)
            return body, info

    def _snapshot(self, location, maximum):
        parent, name = self._parent(location)
        try:
            body, _ = self._read(parent, name, maximum)
            return body
        finally:
            os.close(parent)

    async def snapshot(self, path, binding, *, maximum):
        try:
            return await self._io(self._snapshot, self.location(path, binding), maximum)
        except OSError:
            raise DomainError("FILE_ACCESS_FAILED") from None

    def _read_page(self, location, offset, limit):
        parent, name = self._parent(location)
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(descriptor, "rb") as file:
                before = os.fstat(file.fileno())
                if not stat.S_ISREG(before.st_mode):
                    raise DomainError("FILE_TYPE_OR_SIZE_UNSUPPORTED")
                page, digestor, size = bytearray(), hashlib.sha256(), 0
                while chunk := file.read(64 * 1024):
                    start = max(0, offset - size)
                    end = max(0, offset + limit - size)
                    page.extend(chunk[start:end])
                    digestor.update(chunk)
                    size += len(chunk)
                after = os.fstat(file.fileno())
                if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                ) or size != before.st_size:
                    raise DomainError("FILE_CHANGED", 409)
        finally:
            os.close(parent)
        try:
            text, encoding = page.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            text, encoding = base64.b64encode(page).decode(), "base64"
        return {
            "data": text,
            "encoding": encoding,
            "offsetBytes": offset,
            "readBytes": len(page),
            "sizeBytes": size,
            "sha256": digestor.hexdigest(),
            "nextOffset": offset + len(page) if offset + len(page) < size else None,
        }

    def _read_lines(self, location, offset, limit):
        parent, name = self._parent(location)
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(descriptor, "rb") as file:
                return read_line_page(file, offset, limit)
        finally:
            os.close(parent)

    def _modify(self, location, expected, content, replacement):
        parent, name = self._parent(location)
        temporary, published = ".roami-write-" + identity(), False
        try:
            try:
                original, info = self._read(parent, name)
            except FileNotFoundError:
                original, info = None, None
            digest = hashlib.sha256(original).hexdigest() if original is not None else None
            if expected is CURRENT_CONTENT:
                expected = digest
            if digest != expected:
                raise DomainError("FILE_CHANGED", 409)
            if replacement is not None:
                if original is None:
                    raise DomainError("FILE_NOT_FOUND", 404)
                try:
                    old = original.decode("utf-8")
                except UnicodeDecodeError:
                    raise DomainError("FILE_ENCODING_UNSUPPORTED") from None
                if not content or old.count(content) != 1:
                    raise DomainError("FILE_PATCH_AMBIGUOUS", 409)
                body = old.replace(content, replacement, 1).encode()
            else:
                body = content.encode()
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent
            )
            with os.fdopen(descriptor, "wb") as file:
                file.write(body)
                if info:
                    os.fchmod(file.fileno(), stat.S_IMODE(info.st_mode) & 0o777)
                file.flush()
                os.fsync(file.fileno())
            if original is None:
                try:
                    os.link(
                        temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False
                    )
                except FileExistsError:
                    raise DomainError("FILE_CHANGED", 409) from None
            else:
                current, _ = self._read(parent, name)
                if hashlib.sha256(current).hexdigest() != expected:
                    raise DomainError("FILE_CHANGED", 409)
                os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            published = True
            os.fsync(parent)
            return {
                "sha256": hashlib.sha256(body).hexdigest(),
                "previousSha256": digest,
                "sizeBytes": len(body),
            }
        except OSError:
            if published:
                raise DomainError("TOOL_OUTCOME_UNKNOWN") from None
            raise DomainError("FILE_ACCESS_FAILED") from None
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except OSError:
                pass
            finally:
                os.close(parent)

    async def read(self, args, binding):
        try:
            lines = (
                binding.get("fileReadLines")
                and args.get("offset", 1) != 0
                and args.get("limit", 2000) <= 2000
            )
            result = await self._io(
                self._read_lines if lines else self._read_page,
                self.location(args["path"], binding),
                args.get("offset", 1 if lines else 0),
                args.get("limit", 2000 if lines else 16000),
            )
            self._remember(args, binding, result)
            return result
        except OSError:
            raise DomainError("FILE_ACCESS_FAILED") from None

    def _observation_key(self, path, binding):
        root, parts = self.location(path, binding)
        return (
            binding.get("owner"),
            binding.get("conversation"),
            binding.get("taskId"),
            binding.get("turnId"),
            str(root.joinpath(*parts)),
        )

    def _remember(self, args, binding, result):
        if self.db is None or not binding.get("toolCallId"):
            self.observed[self._observation_key(args["path"], binding)] = result["sha256"]

    async def _expected(self, args, binding):
        if "expectedSha256" in args:
            return None if args["expectedSha256"] == "null" else args["expectedSha256"]
        if self.db is not None and binding.get("turnId"):
            root, parts = self.location(args["path"], binding)
            paths = {args["path"], str(root.joinpath(*parts)), "/".join(parts)}
            observed = await self.db.call(
                lambda db: row(
                    db,
                    "SELECT json_extract(json_extract(native_content(m.content_json),'$.text'),'$.sha256') AS sha256 "
                    "FROM tool_calls x JOIN messages m ON m.id=x.result_message_id "
                    "JOIN turns t ON t.id=x.turn_id JOIN conversations c ON c.id=t.conversation_id "
                    "WHERE x.turn_id=? AND c.owner_id=? AND x.state='succeeded' "
                    "AND x.tool_name IN ('file_read','file_write','file_patch') "
                    "AND json_extract(x.arguments_json,'$.path') IN (?,?,?) ORDER BY x.rowid DESC LIMIT 1",
                    (
                        binding["turnId"],
                        binding.get("owner"),
                        *sorted(paths),
                        *([None] * (3 - len(paths))),
                    ),
                )
            )
            if observed and observed["sha256"]:
                return observed["sha256"]
        return self.observed.get(self._observation_key(args["path"], binding), CURRENT_CONTENT)

    async def write(self, args, binding):
        # Some providers quote JSON null; this alias keeps the same exclusive-create fence.
        expected = await self._expected(args, binding)
        try:
            result = await self._io(
                self._modify,
                self.location(args["path"], binding),
                expected,
                args["content"],
                None,
            )
            self._remember(args, binding, result)
            return result
        except OSError:
            raise DomainError("FILE_ACCESS_FAILED") from None

    async def patch(self, args, binding):
        try:
            result = await self._io(
                self._modify,
                self.location(args["path"], binding),
                await self._expected(args, binding),
                args["oldText"],
                args["newText"],
            )
            self._remember(args, binding, result)
            return result
        except OSError:
            raise DomainError("FILE_ACCESS_FAILED") from None

    async def close(self):
        self.closed = True
        await asyncio.gather(
            *(asyncio.shield(future) for future in tuple(self.pending)), return_exceptions=True
        )
        self.pool.shutdown(wait=True)
