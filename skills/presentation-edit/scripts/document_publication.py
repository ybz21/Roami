"""Publish a separate document inside an explicit workspace with observed hashes."""

import hashlib
import os
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path


class PublicationError(ValueError):
    def __init__(self, code, *, published=False):
        super().__init__(code)
        self.published = published


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise PublicationError("WORKSPACE_REQUIRED")

    def relative(self, path):
        path = Path(path)
        if path.is_absolute():
            try:
                path = path.relative_to(self.root)
            except ValueError:
                raise PublicationError("PATH_OUTSIDE_WORKSPACE") from None
        if not path.parts or ".." in path.parts:
            raise PublicationError("PATH_OUTSIDE_WORKSPACE")
        return path

    @contextmanager
    def parent(self, path):
        relative = self.relative(path)
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in relative.parts[:-1]:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
                os.close(descriptor)
                descriptor = child
            yield descriptor, relative.name
        finally:
            os.close(descriptor)

    @staticmethod
    def read_at(parent, name, *, maximum):
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
        )
        with os.fdopen(descriptor, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
                raise PublicationError("DOCUMENT_SIZE_OR_TYPE_UNSUPPORTED")
            body = source.read(maximum + 1)
            if len(body) > maximum:
                raise PublicationError("DOCUMENT_SIZE_OR_TYPE_UNSUPPORTED")
            return body, info

    def read(self, path, *, maximum=64 * 1024 * 1024):
        with self.parent(path) as (parent, name):
            return self.read_at(parent, name, maximum=maximum)[0]

    def publish(self, source, source_hash, destination, expected, body):
        if self.relative(source) == self.relative(destination):
            raise PublicationError("OUTPUT_MUST_DIFFER")
        temporary, published = ".presentation-" + uuid.uuid4().hex, False
        with self.parent(destination) as (parent, name):
            try:
                try:
                    original, info = self.read_at(
                        parent, name, maximum=128 * 1024 * 1024
                    )
                except FileNotFoundError:
                    original, info = None, None
                previous = (
                    None if original is None else hashlib.sha256(original).hexdigest()
                )
                if previous != expected:
                    raise PublicationError("DESTINATION_CHANGED")
                descriptor = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=parent,
                )
                with os.fdopen(descriptor, "wb") as output:
                    output.write(body)
                    if info:
                        os.fchmod(output.fileno(), stat.S_IMODE(info.st_mode) & 0o777)
                    output.flush()
                    os.fsync(output.fileno())
                if info:
                    current, _ = self.read_at(parent, name, maximum=128 * 1024 * 1024)
                    if hashlib.sha256(current).hexdigest() != expected:
                        raise PublicationError("DESTINATION_CHANGED")
                if hashlib.sha256(self.read(source)).hexdigest() != source_hash:
                    raise PublicationError("SOURCE_CHANGED")
                if original is None:
                    try:
                        os.link(
                            temporary,
                            name,
                            src_dir_fd=parent,
                            dst_dir_fd=parent,
                            follow_symlinks=False,
                        )
                    except FileExistsError:
                        raise PublicationError("DESTINATION_CHANGED") from None
                else:
                    os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
                published = True
                os.fsync(parent)
                return {
                    "path": str(self.relative(destination)),
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "sourceSha256": source_hash,
                    "previousSha256": previous,
                    "sizeBytes": len(body),
                    "writePublished": True,
                }
            except OSError:
                raise PublicationError(
                    "PUBLICATION_UNKNOWN" if published else "FILE_ACCESS_FAILED",
                    published=published,
                ) from None
            finally:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass
                except OSError:
                    raise PublicationError(
                        "PUBLICATION_UNKNOWN" if published else "FILE_ACCESS_FAILED",
                        published=published,
                    ) from None
