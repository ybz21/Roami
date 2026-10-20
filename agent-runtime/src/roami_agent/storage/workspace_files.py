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


class WorkspaceFiles:
    def __init__(self, settings):
        self.settings = settings
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-files")
        self.capacity = asyncio.Semaphore(4)
        self.pending = set()
        self.closed = False

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

    def _read(self, parent, name):
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise DomainError("FILE_TYPE_OR_SIZE_UNSUPPORTED")
            body = file.read()
            after = os.fstat(file.fileno())
            if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise DomainError("FILE_CHANGED", 409)
            return body, info

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

    def _modify(self, location, expected, content, replacement):
        parent, name = self._parent(location)
        temporary, published = ".roami-write-" + identity(), False
        try:
            try:
                original, info = self._read(parent, name)
            except FileNotFoundError:
                original, info = None, None
            digest = hashlib.sha256(original).hexdigest() if original is not None else None
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
            return await self._io(
                self._read_page,
                self.location(args["path"], binding),
                args.get("offset", 0),
                args.get("limit", 16000),
            )
        except OSError:
            raise DomainError("FILE_ACCESS_FAILED") from None

    async def write(self, args, binding):
        try:
            return await self._io(
                self._modify,
                self.location(args["path"], binding),
                args["expectedSha256"],
                args["content"],
                None,
            )
        except OSError:
            raise DomainError("FILE_ACCESS_FAILED") from None

    async def patch(self, args, binding):
        try:
            return await self._io(
                self._modify,
                self.location(args["path"], binding),
                args["expectedSha256"],
                args["oldText"],
                args["newText"],
            )
        except OSError:
            raise DomainError("FILE_ACCESS_FAILED") from None

    async def close(self):
        self.closed = True
        await asyncio.gather(
            *(asyncio.shield(future) for future in tuple(self.pending)), return_exceptions=True
        )
        self.pool.shutdown(wait=True)
