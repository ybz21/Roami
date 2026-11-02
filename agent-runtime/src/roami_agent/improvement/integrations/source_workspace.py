"""Scoped source identity and Git process operations."""

import hashlib
import os
from pathlib import Path

from roami_agent.improvement.domain.contracts import digest, require
from roami_agent.improvement.integrations.artifact_paths import relative_file
from roami_agent.tools.process import execute


async def git(repo, *args, input_data=None):
    result = await execute(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(repo),
            *args,
        ],
        input_data=input_data,
        timeout=60,
        max_bytes=4_000_000,
        env={
            **{
                k: os.environ[k]
                for k in ("PATH", "LANG", "LC_ALL", "TMPDIR", "USER", "LOGNAME")
                if k in os.environ
            },
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        },
    )
    require(result["exitCode"] == 0, "RSI_SOURCE_COMMAND_FAILED")
    return result["stdout"]


def allowed(name, config):
    return (
        isinstance(name, str)
        and name == Path(name).as_posix()
        and Path(name).name not in {".gitattributes", ".gitmodules", ".gitignore", ".git"}
        and name.startswith("agent-runtime/src/roami_agent/")
        and ".." not in Path(name).parts
        and not name.startswith("agent-runtime/src/roami_agent/improvement/")
        and any(name == p or name.startswith(p + "/") for p in config["allowed_paths"])
    )


def source_hash(root):
    package = relative_file(Path(root), "agent-runtime/src/roami_agent")
    require(package.is_dir(), "RSI_SOURCE_PACKAGE_REQUIRED")
    records = {}
    for p in sorted(package.rglob("*")):
        require(not p.is_symlink(), "RSI_SOURCE_SYMLINK")
        if p.is_file() and "__pycache__" not in p.parts:
            records[str(p.relative_to(package))] = hashlib.sha256(p.read_bytes()).hexdigest()

    return digest(records)
