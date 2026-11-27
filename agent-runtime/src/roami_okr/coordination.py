"""Project guidance for admitted daily coordination turns."""


def daily_guidance(value):
    if not value.get("dailySlot") or not value["delegation"].get("projectId"):
        return ""
    return (
        "For an OKR project, first read swarm_project_context and the project's declared daily Skill "
        "and phase prompt. The standard bundle uses .roami/okr/skills/daily-operations/SKILL.md, "
        "with .roami/okr/skills/daily-operations/prompts/kickoff.md for kickoff and "
        ".roami/okr/skills/daily-operations/prompts/review.md for reflection. Read these as "
        "project files, not guessed skill:// names; a phase prompt does not replace the Skill body. "
        "Customized projects use their declared paths. Resolve package-relative prompt paths "
        "from the directory containing SKILL.md, not from .roami/okr/. "
        "Never construct a file path from an arbitrary slot. "
        "For reflection authorized by the stored goal, use swarm_project_update operation=review "
        "at the current revision to save a truthful reflection. Append only new verified "
        "knowledge with swarm_memory_write, using the sha256 just read from swarm_memory_read, "
        "then reread its receipt. These batch wrappers preserve append and review identities; "
        "ordinary project write operations are unavailable in this batch. No new knowledge means no "
        "duplicate memory append. Evidence of an earlier action or a group progress post "
        "is not a saved reflection. "
        "Keep unknown data unknown and report missing workflow or capabilities accurately; "
        "none of these steps expands the authorized scope. "
    )
