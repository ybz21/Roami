"""Snapshot chosen video inputs and publish new workspace deliverables."""

import hashlib
import os
import stat
from pathlib import Path


class MediaError(ValueError):
    pass


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise MediaError("WORKSPACE_REQUIRED")

    def path(self, value, *, exists=True):
        path = Path(value)
        if path.is_absolute():
            try:
                path = path.relative_to(self.root)
            except ValueError:
                raise MediaError("PATH_OUTSIDE_WORKSPACE") from None
        if not path.parts or ".." in path.parts:
            raise MediaError("PATH_OUTSIDE_WORKSPACE")
        current = self.root
        for part in path.parts:
            current = current / part
            if current.is_symlink():
                raise MediaError("SYMLINK_UNSUPPORTED")
        if exists and not current.is_file():
            raise MediaError("FILE_REQUIRED")
        return current

    def parent(self, path, *, create=False):
        parts = self.path(path, exists=False).relative_to(self.root).parts
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                if create:
                    try:
                        os.mkdir(part, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
                os.close(descriptor)
                descriptor = child
            return descriptor, parts[-1]
        except BaseException:
            os.close(descriptor)
            raise

    def snapshot(self, value, destination, expected=None):
        path = self.path(value)
        parent, name = self.parent(path)
        try:
            descriptor = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
            )
        finally:
            os.close(parent)
        with os.fdopen(descriptor, "rb") as source, destination.open("xb") as output:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise MediaError("REGULAR_FILE_REQUIRED")
            remaining = before.st_size + 1
            digest = hashlib.sha256()
            copied = 0
            while remaining:
                body = source.read(min(remaining, 1024 * 1024))
                if not body:
                    break
                digest.update(body)
                output.write(body)
                copied += len(body)
                remaining -= len(body)
            after = os.fstat(source.fileno())
        if copied != before.st_size or (
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise MediaError("SOURCE_CHANGED")
        actual = digest.hexdigest()
        if expected is not None and actual != expected:
            raise MediaError("SOURCE_CHANGED")
        return {"path": str(path.relative_to(self.root)), "sha256": actual}

    def publish(self, staged, sources):
        targets = [self.path(name, exists=False) for name in staged]
        if len(set(targets)) != len(targets):
            raise MediaError("OUTPUT_PATHS_DUPLICATE")
        if any(path.exists() for path in targets):
            raise MediaError("OUTPUT_EXISTS")
        if set(targets) & {self.path(item["path"]) for item in sources}:
            raise MediaError("OUTPUT_IS_SOURCE")
        for item in sources:
            if sha256(self.path(item["path"])) != item["sha256"]:
                raise MediaError("SOURCE_CHANGED")
        parents = []
        published = []
        try:
            for path, temp in zip(targets, staged.values(), strict=True):
                parent, name = self.parent(path, create=True)
                parents.append(parent)
                os.link(temp, name, dst_dir_fd=parent, follow_symlinks=False)
                published.append(
                    (
                        parent,
                        name,
                        os.stat(name, dir_fd=parent, follow_symlinks=False).st_ino,
                    )
                )
        except BaseException:
            for parent, name, inode in reversed(published):
                if os.stat(name, dir_fd=parent, follow_symlinks=False).st_ino == inode:
                    os.unlink(name, dir_fd=parent)
            raise
        finally:
            for parent in parents:
                os.close(parent)
        return [
            {
                "path": str(path.relative_to(self.root)),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in targets
        ]
