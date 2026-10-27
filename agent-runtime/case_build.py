"""Ship the canonical case directory in wheels and source distributions."""

import os
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CaseBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if os.environ.get("ROAMI_RSI_CONTAINER_BUILD") == "1":
            return
        root = Path(self.root)
        cases = root / "cases"
        if not cases.is_dir():
            cases = root.parent / "cases"
        if not cases.is_dir():
            raise FileNotFoundError("Canonical cases/ directory is required for runtime packaging")
        destination = "roami_agent/improvement/cases" if self.target_name == "wheel" else "cases"
        build_data["force_include"][str(cases)] = destination
