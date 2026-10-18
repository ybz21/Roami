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
            references = {}
            for reference in sorted((resolved.parent / "references").glob("*.md")):
                target = reference.resolve()
                if (
                    target.parent != resolved.parent / "references"
                    or target.stat().st_size > 64_000
                ):
                    continue
                content = target.read_text()
                references["references/" + reference.name] = {
                    "text": content,
                    "version": hashlib.sha256(content.encode()).hexdigest(),
                }
            digest = hashlib.sha256(text.encode())
            for reference, content in references.items():
                digest.update(("\0" + reference + "\0" + content["version"]).encode())
            name = path.parent.name
            if name in skills:
                raise DomainError("DUPLICATE_SKILL")
            skills[name] = {
                "text": text,
                "version": digest.hexdigest(),
                "references": references,
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
            if args.get("reference"):
                reference = value["references"].get(args["reference"])
                if not reference:
                    raise DomainError("SKILL_REFERENCE_NOT_FOUND", 404)
                return {**reference, "skillVersion": value["version"]}
            return {"text": value["text"], "version": value["version"]}

        registry.add(
            Tool(
                "skill_read",
                "Read a workflow skill when needed. roami-dispatch covers project/session routing; web-research covers current public information through Roami Chrome CLI. Available: "
                + ", ".join(skills),
                object_schema(
                    {
                        "name": {"type": "string", "enum": list(skills)},
                        "reference": {
                            "type": "string",
                            "pattern": r"^references/[a-zA-Z0-9_-]+\.md$",
                        },
                    },
                    ["name"],
                ),
                skill,
                main=True,
            )
        )
