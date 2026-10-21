"""Navigation-only tool admission for resource-only web research."""

from roami_agent.protocol.skill_names import skill_location

RESEARCH_TOOLS = {
    "tool_list",
    "skill_read",
    "browser_open",
    "browser_observe",
    "browser_act",
    "command_help",
}


def research_call_allowed(name, args):
    if name not in RESEARCH_TOOLS:
        return False
    if name == "skill_read":
        return skill_location(args.get("name"))[0] == "browser_use"
    if name == "browser_open":
        return not args.get("targetId")
    if name == "browser_act":
        return args.get("kind") == "goto"
    return True
