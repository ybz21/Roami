"""Bounded skill bundles retained with their scripts, references and source revision."""

import base64
import binascii
import hashlib
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded

MAX_PACKAGE_BYTES = 384_000


def package_files(value):
    files = value.get("files", {})
    if not isinstance(files, dict) or len(files) > 100:
        raise DomainError("INVALID_SKILL_PACKAGE")
    result, size = {}, 0
    for name, content in files.items():
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 240
            or "\\" in name
            or "\0" in name
            or PurePosixPath(name).is_absolute()
            or any(part in {"", ".", ".."} for part in name.split("/"))
            or not isinstance(content, str)
        ):
            raise DomainError("INVALID_SKILL_PACKAGE")
        try:
            raw = base64.b64decode(content, validate=True)
        except (ValueError, binascii.Error):
            raise DomainError("INVALID_SKILL_PACKAGE") from None
        size += len(raw)
        if size > MAX_PACKAGE_BYTES:
            raise DomainError("CAPABILITY_IMPORT_TOO_LARGE", 413)
        result[name] = raw
    paths = set(result)
    if any(
        str(parent) in paths | {"SKILL.md"}
        for name in paths
        for parent in PurePosixPath(name).parents
    ):
        raise DomainError("INVALID_SKILL_PACKAGE")
    return result


def materialize_package(root, value):
    if not value.get("files"):
        return None
    files = {**package_files(value), "SKILL.md": value["text"].encode()}
    digest = hashlib.sha256(encoded(value).encode()).hexdigest()
    agents = Path(root) / "agents"
    parent = agents / "capability-packages"
    for directory in (agents, parent):
        directory.mkdir(exist_ok=True, mode=0o700)
        info = directory.lstat()
        if (
            directory.is_symlink()
            or not directory.is_dir()
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            raise DomainError("CAPABILITY_IMPORT_PRIVATE_FILE_REQUIRED", 503)
    target = parent / digest
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_dir():
            raise DomainError("INVALID_SKILL_PACKAGE")
        for name, content in files.items():
            path = target / name
            if (
                any(part.is_symlink() for part in (path, *path.parents))
                or not path.is_file()
                or path.read_bytes() != content
            ):
                raise DomainError("INVALID_SKILL_PACKAGE")
        return str(target)
    temporary = Path(tempfile.mkdtemp(prefix=".skill-", dir=parent))
    try:
        for name, content in files.items():
            path = temporary / name
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with path.open("xb") as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return str(target)
