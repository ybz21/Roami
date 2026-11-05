"""Versioned workflow instructions available to Main and workers."""

import hashlib
import re
from pathlib import Path

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.skill_names import SKILL_ALIASES, skill_location
from roami_agent.protocol.tools import Tool, object_schema


def register_skills(registry, settings):
    skills = registry.skills
    builtin = Path(__file__).resolve().parents[1] / "skills"
    roots = [(builtin, tuple(builtin.glob("*/SKILL.md")), "builtin")]
    if not (builtin / "okr-development/SKILL.md").is_file():
        project = Path(__file__).resolve().parents[3]
        for source in (project.parent / "skills", project / "skills"):
            entry = source / "okr-development/SKILL.md"
            if entry.is_file():
                roots.append((source, (entry,), "builtin"))
                break
    roots.extend(
        (root, tuple(root.glob("*/SKILL.md")), "configured") for root in settings.skill_roots
    )
    for root, entries, origin in roots:
        if not root.is_dir():
            continue
        for path in entries:
            resolved = path.resolve()
            if root not in resolved.parents or resolved.stat().st_size > 64_000:
                continue
            text = resolved.read_text()
            references = {}
            resources = [
                path
                for name in ("references", "assets", "parts", "examples")
                for path in (resolved.parent / name).rglob("*")
                if path.is_file()
                and path.suffix in {".md", ".json", ".jsonl", ".html", ".css", ".js", ".py"}
            ]
            for reference in sorted(resources):
                target = reference.resolve()
                if (
                    not target.is_relative_to(resolved.parent)
                    or reference.is_symlink()
                    or target.stat().st_size > 64_000
                ):
                    continue
                try:
                    content = target.read_text()
                except UnicodeDecodeError:
                    continue
                references[reference.relative_to(resolved.parent).as_posix()] = {
                    "text": content,
                    "version": hashlib.sha256(content.encode()).hexdigest(),
                }
            digest = hashlib.sha256(text.encode())
            for reference, content in references.items():
                digest.update(("\0" + reference + "\0" + content["version"]).encode())
            name = path.parent.name
            if name in skills or name in SKILL_ALIASES:
                raise DomainError("DUPLICATE_SKILL")
            skills[name] = {
                "text": text,
                "version": digest.hexdigest(),
                "references": references,
                "source": origin,
                **({"packagePath": str(resolved.parent)} if origin != "builtin" else {}),
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
        reference_pattern = r"^[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*$"

        async def skill(args, binding):
            name, reference_path = skill_location(args["name"], args.get("reference", ""))
            if name in registry.disabled_skills:
                raise DomainError("SKILL_DISABLED")
            value = skills[name]
            if reference_path:
                reference = value["references"].get(reference_path)
                if not reference:
                    raise DomainError("SKILL_REFERENCE_NOT_FOUND", 404)
                return {**reference, "skillVersion": value["version"]}
            return {
                "text": value["text"],
                "version": value["version"],
                "resources": [
                    "skill://" + name + "/" + path
                    for path in sorted(value["references"])
                    if re.fullmatch(reference_pattern, path)
                ],
                **({"packagePath": value["packagePath"]} if value.get("packagePath") else {}),
            }

        registry.add(
            Tool(
                "skill_read",
                "Read a workflow skill when needed. roami covers Roami operations; browser_use covers roami chrome and public research. Available: "
                + ", ".join(skills),
                object_schema(
                    {
                        "name": {"type": "string", "enum": [*skills, *SKILL_ALIASES]},
                        "reference": {
                            "type": "string",
                            "pattern": reference_pattern,
                        },
                    },
                    ["name"],
                ),
                skill,
                main=True,
            )
        )
