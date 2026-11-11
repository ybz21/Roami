"""Publish a reviewed, immutable skill bundle to local Agent discovery directories."""

import os
from pathlib import Path

from roami_agent.protocol.errors import DomainError
from roami_agent.server.skill_package import materialize_package


def skill_directories():
    home = Path.home()
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude")
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    roots = {
        "local": home / ".agents" / "skills",
        "claude": claude / "skills",
        "opencode": config / "opencode" / "skills",
    }
    if any(not path.is_absolute() for path in roots.values()):
        raise DomainError("INVALID_SKILL_TARGET")
    return roots


async def install_skill(runtime, owner, entry, targets):
    roots = skill_directories()
    if (
        not isinstance(targets, list)
        or not targets
        or len(targets) > 4
        or any(not isinstance(target, str) or target not in {*roots, "roami"} for target in targets)
        or len(set(targets)) != len(targets)
    ):
        raise DomainError("INVALID_SKILL_TARGET")
    imports = runtime.capability_imports
    saved = imports.saved["skills"].get(entry["name"])
    if "roami" in targets and saved != entry:
        imports.check_collisions({"skills": {entry["name"]: entry}})
    destinations = {key: roots[key] / entry["name"] for key in targets if key != "roami"}
    created = []
    try:
        package = Path(materialize_package(runtime.db.data_root, entry, force=True))
        for path in destinations.values():
            if path.is_symlink() and path.resolve() == package:
                continue
            if path.exists() or path.is_symlink():
                raise DomainError("SKILL_TARGET_EXISTS", 409)
        for path in destinations.values():
            if path.is_symlink() and path.resolve() == package:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                path.symlink_to(package, target_is_directory=True)
            except FileExistsError:
                raise DomainError("SKILL_TARGET_EXISTS", 409) from None
            created.append(path)
        if "roami" in targets and saved != entry:
            await imports.save(owner, "skills", entry)
    except BaseException as exc:
        for path in reversed(created):
            if path.is_symlink() and path.resolve() == package:
                path.unlink()
        if isinstance(exc, OSError):
            raise DomainError("SKILL_INSTALL_FAILED", 503) from None
        raise
    return {
        "kind": "skills",
        "name": entry["name"],
        "origin": entry["origin"],
        "state": "installed",
        "targets": targets,
        "locations": {key: str(path) for key, path in destinations.items()},
    }
