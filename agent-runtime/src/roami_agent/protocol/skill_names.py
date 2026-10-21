"""Canonical built-in names and read compatibility for existing conversations."""

SKILL_ALIASES = {"roami-dispatch": "roami", "web-research": "browser_use"}


def skill_location(name, reference=""):
    if name == "roami-dispatch" and reference == "references/chrome.md":
        return "browser_use", "references/chrome-cli.md"
    return SKILL_ALIASES.get(name, name), reference
