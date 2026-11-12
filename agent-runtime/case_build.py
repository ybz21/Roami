"""Ship canonical evaluation cases and OKR authoring resources."""

import os
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CaseBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        prompts = root / "prompts"
        if not prompts.is_dir():
            prompts = root.parent / "backend/api/prompts"
        for name in (
            "agent-capabilities.md",
            "task-execution.md",
            "task-report-managed.md",
            "task-report-session.md",
            "task-report-legacy.md",
            "task-report-swarm.md",
        ):
            source = prompts / name
            if not source.is_file():
                raise FileNotFoundError(f"Canonical execution prompt is required: {name}")
            destination = "roami_agent/prompts/" if self.target_name == "wheel" else "prompts/"
            build_data["force_include"][str(source)] = destination + name
        skill = root / "skills/okr-development"
        if not skill.is_dir():
            skill = root.parent / "skills/okr-development"
        if not (skill / "SKILL.md").is_file():
            raise FileNotFoundError("Canonical skills/okr-development is required for packaging")
        destination = (
            "roami_agent/skills/okr-development"
            if self.target_name == "wheel"
            else "skills/okr-development"
        )
        build_data["force_include"][str(skill)] = destination
        if os.environ.get("ROAMI_RSI_CONTAINER_BUILD") == "1":
            return
        cases = root / "cases"
        if not cases.is_dir():
            cases = root.parent / "cases"
        if not cases.is_dir():
            raise FileNotFoundError("Canonical cases/ directory is required for runtime packaging")
        destination = "roami_agent/improvement/cases" if self.target_name == "wheel" else "cases"
        build_data["force_include"][str(cases)] = destination
