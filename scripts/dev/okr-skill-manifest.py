#!/usr/bin/env python3
"""Refresh the native installer manifest for the canonical OKR Skill."""

import hashlib
from pathlib import Path

package = Path(__file__).resolve().parents[2] / "skills/okr-development"
files = []
for path in sorted(package.rglob("*")):
    if not path.is_file() or path.name == "package.files" or "__pycache__" in path.parts:
        continue
    if path.is_symlink():
        raise ValueError("Skill resources must be regular files")
    files.append(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(package).as_posix()}"
    )
(package / "package.files").write_text("\n".join(files) + "\n")
