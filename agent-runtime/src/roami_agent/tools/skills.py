"""Versioned workflow instructions available to Main and workers."""

import hashlib
from pathlib import Path

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.tools import Tool, object_schema


def register_skills(registry, settings):
    skills = registry.skills
    builtin = Path(__file__).resolve().parents[1] / "skills"
    for root in (builtin, *settings.skill_roots):
        if not root.is_dir():
            continue
        for path in root.glob("*/SKILL.md"):
            resolved = path.resolve()
            if root not in resolved.parents or resolved.stat().st_size > 64_000:
                continue
            text = resolved.read_text()
            name = path.parent.name
            if name in skills:
                raise DomainError("DUPLICATE_SKILL")
            skills[name] = {
                "text": text,
                "version": hashlib.sha256(text.encode()).hexdigest(),
                "source": "builtin" if root == builtin else "configured",
                "description": next(
                    (
                        line.partition(":")[2].strip().strip("\"'")
                        for line in text.splitlines()
                        if line.startswith("description:")
                    ),
                    "",
                ),
            }
    if skills:

        async def skill(args, binding):
            if args["name"] in registry.disabled_skills:
                raise DomainError("SKILL_DISABLED")
            value = skills[args["name"]]
            return {"text": value["text"], "version": value["version"]}

        registry.add(
            Tool(
                "skill_read",
                "Read a workflow skill when needed. roami-dispatch covers project/session routing; web-research covers current public information through Roami Chrome CLI. Available: "
                + ", ".join(skills),
                object_schema({"name": {"type": "string", "enum": list(skills)}}, ["name"]),
                skill,
                main=True,
            )
        )
