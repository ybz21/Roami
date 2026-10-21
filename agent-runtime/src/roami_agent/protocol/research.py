"""Read-only tool admission for resource-only web research."""

from roami_agent.protocol.skill_names import skill_location

RESEARCH_TOOLS = {
    "tool_list",
    "skill_read",
    "browser_open",
    "browser_observe",
    "browser_act",
    "command_help",
    "mcp_discover",
}


def read_only_mcp_available(registry):
    return any(
        tool.name not in registry.disabled_tools
        and (tool.name == "mcp_discover" or tool.name.startswith("mcp_") and tool.effect == "read")
        for tool in registry.registry.values()
    )


def research_call_allowed(name, args, *, effect=None):
    if name.startswith("mcp_") and name != "mcp_discover":
        return effect == "read"
    if name not in RESEARCH_TOOLS:
        return False
    if name == "skill_read":
        return skill_location(args.get("name"))[0] == "browser_use"
    if name == "browser_open":
        return not args.get("targetId")
    if name == "browser_act":
        return args.get("kind") == "goto"
    return True
