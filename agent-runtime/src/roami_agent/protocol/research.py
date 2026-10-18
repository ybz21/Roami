"""Navigation-only tool admission for resource-only web research."""

RESEARCH_TOOLS = {"skill_read", "browser_open", "browser_observe", "browser_act"}


def research_call_allowed(name, args):
    if name not in RESEARCH_TOOLS:
        return False
    if name == "skill_read":
        return args.get("name") == "web-research"
    if name == "browser_open":
        return not args.get("targetId")
    if name == "browser_act":
        return args.get("kind") == "goto"
    return True
