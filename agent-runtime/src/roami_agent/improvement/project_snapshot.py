"""Bounded repository snapshots that cannot follow agent-created host symlinks."""

import hashlib
import io
import os
import stat
import tarfile
from pathlib import PurePosixPath

from roami_agent.improvement.contracts import require

MAX_PROJECT_BYTES = 300_000_000


def copy_project_snapshot(source, target):
    target.mkdir(mode=0o700)
    total, count, entries, records = 0, 0, 0, []

    def visit(descriptor, destination, prefix):
        nonlocal total, count, entries
        for entry in sorted(os.scandir(descriptor), key=lambda item: item.name):
            require(entry.name not in {".", ".."})
            if entry.name == ".git":
                continue
            entries += 1
            require(entries <= 25000 and prefix.count("/") <= 64, "RSI_INPUT_TOO_LARGE")
            mode = entry.stat(follow_symlinks=False).st_mode
            if stat.S_ISDIR(mode):
                child = os.open(
                    entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                )
                try:
                    (destination / entry.name).mkdir(mode=0o700)
                    visit(child, destination / entry.name, prefix + entry.name + "/")
                finally:
                    os.close(child)
            else:
                require(stat.S_ISREG(mode), "RSI_PROJECT_SPECIAL_FILE")
                child = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
                try:
                    info = os.fstat(child)
                    require(
                        stat.S_ISREG(info.st_mode) and info.st_size <= 20_000_000,
                        "RSI_INPUT_TOO_LARGE",
                    )
                    total += info.st_size
                    count += 1
                    require(total <= MAX_PROJECT_BYTES and count <= 20000, "RSI_INPUT_TOO_LARGE")
                    with os.fdopen(os.dup(child), "rb") as file:
                        data = file.read(20_000_001)
                    require(len(data) <= info.st_size, "RSI_PROJECT_CHANGED_DURING_COPY")
                    path = destination / entry.name
                    path.write_bytes(data)
                    path.chmod(0o600 | (info.st_mode & 0o100))
                    records.append((prefix + entry.name, hashlib.sha256(data).hexdigest()))
                finally:
                    os.close(child)

    descriptor = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        visit(descriptor, target, "")
    finally:
        os.close(descriptor)
    from roami_agent.improvement.contracts import digest

    return {"sha256": digest(records), "files": count, "bytes": total}


def unpack_project(archive, destination):
    destination.mkdir(mode=0o700)
    count, size, entries, seen = 0, 0, 0, set()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        for member in bundle:
            entries += 1
            require(entries <= 25000, "RSI_INPUT_TOO_LARGE")
            path = PurePosixPath(member.name)
            require(
                not path.is_absolute()
                and ".." not in path.parts
                and path.parts
                and len(path.parts) <= 64,
                "RSI_ARCHIVE_PATH",
            )
            require(member.name not in seen, "RSI_DUPLICATE_SOURCE_ID")
            seen.add(member.name)
            target = destination.joinpath(*path.parts)
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            require(member.isfile() and member.size <= 20_000_000, "RSI_PROJECT_SPECIAL_FILE")
            size += member.size
            count += 1
            require(size <= MAX_PROJECT_BYTES and count <= 20000, "RSI_INPUT_TOO_LARGE")
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with bundle.extractfile(member) as stream:
                data = stream.read(member.size + 1)
            require(len(data) == member.size)
            descriptor = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600 | (member.mode & 0o100),
            )
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
    return {"files": count, "bytes": size}
