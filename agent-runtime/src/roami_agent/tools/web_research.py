"""Main routes live web questions to configured web MCP tools without a code workspace."""

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.tools import Tool, object_schema


def register_research_tools(registry, tasks, mcp):
    def web_lookup(alias, remote):
        name = remote.lower().replace("-", "_")
        if name in {"browser_navigate", "web_search", "search_web", "fetch_url", "web_fetch"}:
            return True
        tool = registry.registry[alias]
        return ("search" in name and "web search" in tool.description.lower()) or (
            "fetch" in name and "url" in tool.schema.get("properties", {})
        )

    def availability():
        worker = set(registry.registry) - registry.disabled_tools
        return (
            (not registry.directory or {"read", "bash"} <= worker)
            and any(
                alias in worker and web_lookup(alias, remote)
                for connection in mcp.connections.values()
                for alias, remote in connection.names.items()
            )
            and "skill_read" in worker
            and "browser_use" in registry.skills
            and "browser_use" not in registry.disabled_skills
        )

    async def capabilities(args, binding):
        return {
            "mainTools": [item["function"]["name"] for item in registry.catalog("main")],
            "backgroundTools": [item["function"]["name"] for item in registry.catalog("worker")],
            "skills": [name for name in registry.skills if name not in registry.disabled_skills],
            "webResearchAvailable": availability()
            and "web_research" not in registry.disabled_tools,
        }

    async def research(args, binding):
        if not availability():
            raise DomainError("WEB_RESEARCH_UNAVAILABLE", 503)
        task = await tasks.create(
            binding["owner"],
            binding["conversation"],
            "Read skill://browser_use, then use the enabled web MCP tools to research this request. "
            "This task has no code workspace; do not request a project or use Shell. Return verified source URLs, retrieval time, and any delayed/stale/blocked status. User request:\n"
            + args["goal"],
            key=binding["turnId"] + ":" + binding["toolCallId"],
            executor="native",
            target={"kind": "new_session", "resourceOnly": True},
            source_turn_id=binding["turnId"],
            source_assistant_message_id=binding["assistantMessageId"],
            parent_task_id=binding.get("taskId"),
            origin_message_id=binding["originMessageId"],
        )
        return {
            "id": task["id"],
            "state": task["state"],
            "acceptedOnly": True,
            "delivery": "pending",
        }

    registry.add(
        Tool(
            "capability_overview",
            "Discover the actual available Main/background tools and skills before claiming a capability is missing. webResearchAvailable tells whether web_research can use configured web MCP tools; never infer background ability from Main's own catalog.",
            object_schema({}),
            capabilities,
            main=True,
        )
    )
    registry.add(
        Tool(
            "web_research",
            "Research current public web information (prices, news, documentation) through configured web MCP tools in a native background task. User lookup requests authorize research; do not ask them to open a browser, create a project, or dispatch Codex. Returns queue acceptance only; the task result returns to this conversation with sources and time. Check capability_overview if unavailable.",
            object_schema(
                {"goal": {"type": "string", "minLength": 1, "maxLength": 19000}}, ["goal"]
            ),
            research,
            main=True,
            effect="write",
        )
    )
