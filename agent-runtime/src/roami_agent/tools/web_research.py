"""Main routes live web questions to read-only MCP or browser research."""

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.research import read_only_mcp_available
from roami_agent.protocol.tools import Tool, object_schema

BROWSER_TOOLS = {"browser_open", "browser_observe", "browser_act"}


def register_research_tools(registry, tasks):
    def availability():
        worker = set(registry.registry) - registry.disabled_tools
        return (not registry.directory or {"read", "bash"} <= worker) and (
            read_only_mcp_available(registry)
            or BROWSER_TOOLS <= worker
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
            "Discover available read-only search MCP tools with tool_list(kind=mcp) and use suitable tools. "
            "Use roami chrome for requested browser navigation or when MCP cannot cover the request; read skill://browser_use as needed. "
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
            "Discover the actual available Main/background tools and skills before claiming a capability is missing. webResearchAvailable tells whether web_research can use Roami Chrome CLI; never infer background ability from Main's own catalog.",
            object_schema({}),
            capabilities,
            main=True,
        )
    )
    registry.add(
        Tool(
            "web_research",
            "Research current public web information through available read-only MCP tools or Roami Chrome in a native background task. No project is required. Returns queue acceptance only; verified sources and retrieval time return to this conversation. Check capability_overview if unavailable.",
            object_schema(
                {"goal": {"type": "string", "minLength": 1, "maxLength": 19000}}, ["goal"]
            ),
            research,
            main=True,
            effect="write",
        )
    )
