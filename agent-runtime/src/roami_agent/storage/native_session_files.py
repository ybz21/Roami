"""Private native journals with atomic metadata and immutable gzip segments."""

import fcntl
import gzip
import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded

SESSION_ID = re.compile(r"[0-9]{8}T[0-9]{9}Z-[a-f0-9]{12}")


class NativeSessionFiles:
    def __init__(self, root):
        self.root = Path(root)

    @contextmanager
    def directory(self, ident, *, lock=True):
        if not SESSION_ID.fullmatch(ident):
            raise DomainError("NATIVE_SESSION_NOT_FOUND", 404)
        self.root.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.mkdir(exist_ok=True, mode=0o700)
        for path in (self.root.parent, self.root):
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise DomainError("NATIVE_DIRECTORY_INVALID", 503)
        parent = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                os.mkdir(ident, mode=0o700, dir_fd=parent)
            except FileExistsError:
                pass
            directory = os.open(ident, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                if not lock:
                    yield directory
                    return
                lock = os.open(
                    ".write.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=directory
                )
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    yield directory
                finally:
                    os.close(lock)
            finally:
                os.close(directory)
        finally:
            os.close(parent)

    @staticmethod
    def replace(directory, name, content):
        temporary = ".write-" + os.urandom(8).hex()
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory
        )
        try:
            with os.fdopen(fd, "wb") as target:
                target.write(content)
                target.flush()
                os.fsync(target.fileno())
            os.rename(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass

    @staticmethod
    def _active(directory):
        fd = os.open(".chat.jsonl", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise DomainError("NATIVE_JOURNAL_INVALID", 503)
        return os.fdopen(fd, "r+b")

    def append(self, ident, records, metadata):
        with self.directory(ident) as directory, self._active(directory) as stream:
            previous, end, last = {}, 0, None
            for line in stream:
                if not line.endswith(b"\n"):
                    stream.truncate(end)
                    break
                try:
                    item = json.loads(line)
                    seq = item["seq"]
                    if (
                        type(seq) is not int
                        or seq < 1
                        or not isinstance(item.get("eventId"), str)
                        or item["nativeSessionId"] != ident
                        or (last is not None and seq != last + 1)
                    ):
                        raise ValueError("journal sequence")
                except (ValueError, KeyError, TypeError) as exc:
                    raise DomainError("NATIVE_JOURNAL_CORRUPT", 503) from exc
                previous[seq] = (item["eventId"], hashlib.sha256(line).hexdigest())
                last, end = seq, stream.tell()
            if metadata["projectedSeq"] > metadata["archivedSeq"] and (
                last is None or last < metadata["projectedSeq"]
            ):
                raise DomainError("NATIVE_JOURNAL_MISSING", 503)
            stream.seek(0, os.SEEK_END)
            written = []
            for item in records:
                data = (encoded(item) + "\n").encode()
                digest = hashlib.sha256(data).hexdigest()
                seq = item["seq"]
                if seq in previous:
                    if previous[seq] != (item["eventId"], digest):
                        raise DomainError("NATIVE_JOURNAL_CONFLICT", 503)
                else:
                    if seq != (last if last is not None else metadata["archivedSeq"]) + 1:
                        raise DomainError("NATIVE_JOURNAL_GAP", 503)
                    stream.write(data)
                    last = seq
                written.append((seq, digest, len(data)))
            stream.flush()
            os.fsync(stream.fileno())
            metadata = dict(
                metadata, projectedSeq=written[-1][0] if written else metadata["projectedSeq"]
            )
            self.replace(directory, ".session.json", (encoded(metadata) + "\n").encode())
            return written

    def seal(self, ident, through, after=0):
        with self.directory(ident) as directory, self._active(directory) as stream:
            archive = bytearray()
            first, last = None, None
            for line in stream:
                record = json.loads(line)
                seq = record["seq"]
                if seq <= after:
                    continue
                if seq > through:
                    break
                first = seq if first is None else first
                last = seq
                archive.extend(line)
                if len(archive) >= 32 * 1024 * 1024:
                    break
            if first is None:
                return None
            name = f"{first:020d}-{last:020d}.jsonl.gz"
            compressed = gzip.compress(bytes(archive), compresslevel=6, mtime=0)
            self.replace(directory, name, compressed)
            return {
                "firstSeq": first,
                "lastSeq": last,
                "filename": name,
                "sha256": hashlib.sha256(compressed).hexdigest(),
                "rawSha256": hashlib.sha256(archive).hexdigest(),
                "rawBytes": len(archive),
                "compressedBytes": len(compressed),
            }

    def trim(self, ident, through, manifest):
        with self.directory(ident) as directory, self._active(directory) as stream:
            remainder = b"".join(line for line in stream if json.loads(line)["seq"] > through)
            self.replace(directory, ".chat.jsonl", remainder)
            self.replace(directory, ".chat.index", (encoded(manifest) + "\n").encode())

    def records(self, ident, segments, after, limit):
        result = []
        with self.directory(ident) as directory:
            for segment in segments:
                if segment["last_seq"] <= after:
                    continue
                raw = self._archive_bytes(directory, segment)
                for line in raw.splitlines():
                    item = json.loads(line)
                    if item["seq"] > after:
                        result.append(item)
                        if len(result) == limit:
                            return result
            archived = segments[-1]["last_seq"] if segments else 0
            with self._active(directory) as source:
                for line in source:
                    item = json.loads(line)
                    if item["seq"] > max(after, archived):
                        result.append(item)
                        if len(result) == limit:
                            break
        return result

    def archive_bytes(self, ident, segment):
        with self.directory(ident, lock=False) as directory:
            return self._archive_bytes(directory, segment)

    @staticmethod
    def _archive_bytes(directory, segment):
        name = segment["filename"]
        if (
            not re.fullmatch(r"[0-9]{20}-[0-9]{20}\.jsonl\.gz", name)
            or not isinstance(segment["raw_bytes"], int)
            or segment["raw_bytes"] < 0
        ):
            raise DomainError("NATIVE_ARCHIVE_INVALID", 503)
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise DomainError("NATIVE_ARCHIVE_INVALID", 503)
            digest = hashlib.file_digest(source, "sha256").hexdigest()
            if digest != segment["sha256"]:
                raise DomainError("NATIVE_ARCHIVE_CORRUPT", 503)
            source.seek(0)
            with gzip.GzipFile(fileobj=source, mode="rb") as compressed:
                raw = compressed.read(segment["raw_bytes"] + 1)
        if (
            len(raw) != segment["raw_bytes"]
            or hashlib.sha256(raw).hexdigest() != segment["raw_sha256"]
        ):
            raise DomainError("NATIVE_ARCHIVE_CORRUPT", 503)
        return raw

    def metadata(self, ident, metadata):
        with self.directory(ident) as directory:
            self.replace(directory, ".session.json", (encoded(metadata) + "\n").encode())
