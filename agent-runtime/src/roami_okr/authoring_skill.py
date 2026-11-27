"""Locate the shipped OKR authoring Skill in a wheel or source checkout."""

from pathlib import Path


def authoring_skill():
    module = Path(__file__).resolve()
    runtime = module.parents[2]
    for directory in (module.parent, runtime.parent, runtime):
        entry = directory / "skills/okr-development/SKILL.md"
        if entry.is_file():
            return (entry,)
    return ()
