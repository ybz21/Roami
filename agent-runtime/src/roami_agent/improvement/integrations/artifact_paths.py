"""Confine file references to an explicit workspace root."""

from pathlib import Path

from roami_agent.improvement.domain.contracts import require


def relative_file(root, name):
    require(isinstance(name, str) and bool(name) and not Path(name).is_absolute())
    path = root / name
    require(".." not in Path(name).parts and path.resolve().is_relative_to(root.resolve()))
    return path
