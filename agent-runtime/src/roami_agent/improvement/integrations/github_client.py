"""Trusted publication configuration and bounded GitHub CLI calls."""

import re
from pathlib import Path

from roami_agent.improvement.domain.contracts import digest, require
from roami_agent.improvement.integrations.artifact_files import private_json
from roami_agent.improvement.integrations.json_documents import load_json
from roami_agent.tools.process import execute


def profile_path(root, owner):
    return Path(root) / "review-publication" / digest(owner)[:24] / "profile.json"


def publication_profile(root, owner):
    path = profile_path(root, owner)
    if not path.exists():
        return None
    require(
        not path.is_symlink() and path.stat().st_mode & 0o077 == 0, "RSI_PRIVATE_PROFILE_REQUIRED"
    )
    value = load_json(path, maximum=65536)
    require(isinstance(value, dict) and set(value) == {"repository", "remote", "base"})
    require(all(isinstance(v, str) for v in value.values()))
    require(
        bool(
            re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", value["repository"]
            )
        )
    )
    require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value["remote"])))
    require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", value["base"])))
    require(".." not in value["base"] and "//" not in value["base"])
    return value


def configure_publication(root, owner, value):
    path = profile_path(root, owner)
    require(not path.exists(), "RSI_PUBLICATION_ALREADY_CONFIGURED")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_json(path, value)
    try:
        return publication_profile(root, owner)
    except BaseException:
        path.unlink()
        raise


async def command(argv, *, data=None, timeout=60):
    result = await execute(
        argv, cwd=Path.cwd(), timeout=timeout, input_data=data, max_bytes=2_000_000
    )
    require(result["exitCode"] == 0, "RSI_PUBLICATION_COMMAND_FAILED")
    return result["stdout"]
