"""Small model-facing tools over the existing CLI-backed application operations."""

import hashlib
import json
import re
import shlex
from copy import deepcopy
from dataclasses import replace

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.research import research_call_allowed
from roami_agent.protocol.serialization import encoded
from roami_agent.protocol.tool_arguments import validate_tool_arguments
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.tools.process import execute

FOUNDATIONS = ("read", "bash", "edit", "write", "tool_list", "delegate", "ask_user")
WORKER_FOUNDATIONS = set(FOUNDATIONS) - {"ask_user", "delegate"}
RESEARCH_FOUNDATIONS = {"read", "bash", "tool_list"}
FILE_OPERATIONS = {"file_read", "file_write", "file_patch", "shell", "skill_read"}
GROUPS = {
    "workspace_overview": "sessions",
    "target_search": "sessions",
    "target_resolve": "sessions",
    "session_send": "sessions",
    "session_dispatch_status": "sessions",
    "task_status": "tasks",
    "task_cancel": "tasks",
    "task_steer": "tasks",
    "capability_overview": "discovery",
    "executor_catalog": "discovery",
}


class ToolDirectory:
    def __init__(self, registry, settings):
        self.registry, self.settings = registry, settings

    def operations(self, role):
        return [
            tool
            for tool in self.registry.registry.values()
            if tool.name not in FOUNDATIONS
            and tool.name not in FILE_OPERATIONS
            and tool.name != "web_research"
            and (role != "main" or tool.main or tool.name == "artifact_read")
            and (
                role != "research"
                or tool.name in {"browser_open", "browser_observe", "browser_act"}
            )
        ]

    def list(self, query="", kind="all", limit=10, role="main", offset=0):
        limit, offset = min(max(limit, 1), 20), max(offset, 0)
        entries = []
        if "read" not in self.registry.disabled_tools:
            for name, value in self.registry.skills.items():
                if (
                    name in self.registry.disabled_skills
                    or role == "research"
                    and name != "web-research"
                ):
                    continue
                entries.append(
                    {
                        "id": "skill:" + name,
                        "kind": "skill",
                        "name": name,
                        "description": value["description"],
                        "version": value["version"],
                        "location": "skill://" + name,
                    }
                )
        if "bash" not in self.registry.disabled_tools:
            for tool in self.operations(role):
                if tool.name in self.registry.disabled_tools:
                    continue
                schema = deepcopy(tool.schema)
                if role == "research":
                    if tool.name == "browser_act":
                        schema["properties"]["kind"]["enum"] = ["goto"]
                        schema["required"] = ["observationId", "kind", "url"]
                    elif tool.name == "browser_open":
                        schema["properties"].pop("targetId", None)
                entries.append(
                    {
                        "id": ("mcp:" if tool.name.startswith("mcp_") else "cli:") + tool.name,
                        "kind": "mcp" if tool.name.startswith("mcp_") else "cli",
                        "name": tool.name,
                        "description": tool.description,
                        "argv": [
                            "roami",
                            "agent",
                            "capability",
                            "call",
                            tool.name,
                            "--input",
                            "JSON",
                        ],
                        "inputSchema": schema,
                        "effect": tool.effect,
                    }
                )
        version = hashlib.sha256(encoded(entries).encode()).hexdigest()
        normalize = lambda value: re.sub(r"[-_\s]+", " ", value.casefold()).strip()
        words = normalize(query).split()
        aliases = {
            "会话": "session target",
            "项目": "project workspace target",
            "派活": "session delegate",
            "消息": "send session",
            "浏览器": "browser web",
            "网页": "browser web",
            "截图": "chrome screenshot",
            "录屏": "chrome recording",
            "标签页": "chrome browser",
            "记忆": "memory",
            "提醒": "reminder",
            "任务": "task",
            "技能": "skill dispatch",
            "能力": "capability overview",
            "联网": "web research browser",
            "天气": "web research weather forecast",
            "股价": "web research stock quote",
            "新闻": "web research news",
            "统计": "workspace overview",
            "总量": "workspace overview",
            "取消": "task cancel reminder",
        }
        terms = set(words)
        for word, alternatives in aliases.items():
            if word in query:
                terms.update(alternatives.split())
        ranked = []
        for item in entries:
            name, description = normalize(item["name"]), normalize(item["description"])
            name_score = sum(term in name.split() for term in terms)
            if item["name"] == "capability_overview" and query and not name_score:
                continue
            score = name_score * 20 + sum(term in description for term in terms)
            if normalize(query) == name:
                score += 1000
            if not query or score:
                ranked.append((score, name_score, item))
        ranked.sort(key=lambda entry: (-entry[0], entry[2]["id"]))
        selected = [entry for entry in ranked if kind == "all" or entry[2]["kind"] == kind]
        alternatives = [entry for entry in ranked if kind != "all" and entry[2]["kind"] != kind]
        if alternatives and alternatives[0][1] and not any(entry[1] for entry in selected):
            selected = []
        result = {
            "scope": "current_role",
            "hint": (
                "Local capabilities callable in this role only, not web search results. Zero matches "
                "do not prove a worker lacks integrations or external services are unavailable. "
                "For requested external facts, retrieve sources through a delegated browser lookup."
            ),
            "catalogVersion": version,
            "items": [item for _, _, item in selected[offset : offset + limit]],
            "total": len(selected),
            "offset": offset,
            "nextOffset": offset + limit if offset + limit < len(selected) else None,
            "totals": {
                category: sum(item["kind"] == category for item in entries)
                for category in ("mcp", "skill", "cli")
            },
            "truncated": offset + limit < len(selected),
        }
        if not selected and alternatives:
            result["suggestions"] = [item for _, _, item in alternatives[:3]]
            result["hint"] += (
                " "
                "No matching "
                + kind
                + " operation. Follow the suggested workflow or capability instead of repeating the same search."
            )
            if any(item["name"] == "web-research" for item in result["suggestions"]):
                result["hint"] += (
                    " web-research is a Skill, not a web_research CLI command. For bounded public lookups Main can directly delegate "
                    "executor=native, target={kind:new_session,resourceOnly:true}, with routing complexity=bounded and a concrete basis. Complex investigations use a professional executor; task examples are open."
                )
        return result

    def groups(self):
        groups = {}
        for tool in self.operations("worker"):
            name = GROUPS.get(tool.name, tool.name.split("_", 1)[0])
            groups.setdefault(name, []).append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "enabled": tool.name not in self.registry.disabled_tools,
                    "source": tool.source,
                    "mutable": tool.source == "external",
                }
            )
        return [{"name": name, "commands": commands} for name, commands in sorted(groups.items())]

    @staticmethod
    def argv(args):
        if "argv" in args:
            return args["argv"]
        try:
            return shlex.split(args["command"])
        except ValueError:
            raise DomainError("INVALID_TOOL_ARGUMENTS") from None

    def operation(self, argv):
        if (
            len(argv) >= 4
            and argv[0] in {"roami", self.settings.cli_bin}
            and argv[1:4] == ["agent", "capability", "call"]
        ):
            if len(argv) != 7 or argv[5] != "--input":
                raise DomainError("INVALID_CLI_ARGUMENTS")
            try:
                return argv[4], json.loads(argv[6])
            except ValueError:
                raise DomainError("INVALID_CLI_ARGUMENTS") from None
        return None

    def resolve(self, tool, args, role):
        if tool.name == "read":
            path = args["path"]
            if path.startswith("skill://"):
                skill, separator, reference = path.removeprefix("skill://").partition("/")
                name, args = "skill_read", {"name": skill}
                if separator:
                    args["reference"] = reference
            elif path.startswith("artifact://"):
                name, args = (
                    "artifact_read",
                    {
                        "id": path.removeprefix("artifact://"),
                        **{key: value for key, value in args.items() if key != "path"},
                    },
                )
            else:
                if role == "research":
                    raise DomainError("TOOL_UNAVAILABLE")
                return replace(self.registry.registry["file_read"], main=True), args
        elif tool.name in {"edit", "write"}:
            name = "file_patch" if tool.name == "edit" else "file_write"
            return replace(self.registry.registry[name], main=True), args
        elif tool.name == "bash":
            operation = self.operation(self.argv(args))
            if operation is None:
                if role == "research":
                    raise DomainError("TOOL_UNAVAILABLE")
                argv = self.argv(args)
                if (
                    argv
                    and argv[0] in {"roami", self.settings.cli_bin}
                    and tuple(argv[1:3])
                    in {
                        ("project", "ls"),
                        ("project", "show"),
                        ("project", "sessions"),
                        ("session", "ls"),
                        ("session", "resolve"),
                    }
                ):
                    return replace(tool, effect="read"), args
                return tool, args
            name, args = operation
            if name not in {item.name for item in self.operations(role)}:
                raise DomainError("TOOL_UNAVAILABLE")
        else:
            return tool, args
        original = self.registry.registry.get(name)
        if not original or name in self.registry.disabled_tools:
            raise DomainError("TOOL_DISABLED" if original else "TOOL_UNAVAILABLE")
        validate_tool_arguments(original.schema, args)
        if role == "research" and not research_call_allowed(name, args):
            raise DomainError("TOOL_UNAVAILABLE")
        return original, args


def register_foundations(registry, settings):
    directory = ToolDirectory(registry, settings)
    registry.directory = directory

    async def list_tools(args, binding):
        return directory.list(
            args.get("query", ""),
            args.get("kind", "all"),
            args.get("limit", 10),
            binding.get("role", "main"),
            args.get("offset", 0),
        )

    async def bash(args, binding):
        argv = directory.argv(args)
        if not argv:
            raise DomainError("INVALID_TOOL_ARGUMENTS")
        if argv[0] in {"roami", settings.cli_bin}:
            allowed = {
                ("project", "ls"),
                ("project", "show"),
                ("project", "sessions"),
                ("session", "ls"),
                ("session", "resolve"),
            }
            help_only = argv[1:] in (["--help"], ["help"], ["agent", "capability", "--help"])
            if tuple(argv[1:3]) not in allowed and not help_only:
                raise DomainError("USE_REGISTERED_CLI_CAPABILITY")
            result = await execute(
                [settings.cli_bin, *argv[1:]],
                timeout=args.get("timeout") or None,
                excluded_env=settings.provider_key_environments(),
            )
            return result
        shell_args = {key: value for key, value in args.items() if key != "command"}
        shell_args["argv"] = ["bash", "-lc", args["command"]] if "command" in args else argv
        return await registry.registry["shell"].handler(shell_args, binding)

    async def resolved_only(args, binding):
        raise DomainError("INVALID_TOOL_ARGUMENTS")

    registry.add(
        Tool(
            "tool_list",
            "List local MCP, Skill and CLI capabilities callable in this role, with name/intent/category filters and pagination. Returns skill:// paths or exact bash argv and schemas. Known operations can run directly. This is not web results or an external service/pricing directory; empty matches do not prevent delegated browser lookup.",
            object_schema(
                {
                    "query": {"type": "string", "maxLength": 1000},
                    "kind": {"enum": ["all", "mcp", "skill", "cli"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    "offset": {"type": "integer", "minimum": 0},
                },
            ),
            list_tools,
            main=True,
        )
    )
    registry.add(
        Tool(
            "read",
            "Read a file, skill://NAME workflow, skill://NAME/references/FILE.md, or artifact://ID. Load only relevant skill references. File access uses the bound workspace or configured roots.",
            registry.registry["file_read"].schema,
            resolved_only,
            main=True,
        )
    )
    registry.add(
        Tool(
            "edit",
            "Apply one exact file replacement after checking expectedSha256. Use read first; ambiguous or changed files are rejected.",
            registry.registry["file_patch"].schema,
            resolved_only,
            main=True,
            effect="write",
        )
    )
    registry.add(
        Tool(
            "write",
            "Atomically write a workspace file. New file: prefer expectedSha256 as JSON null (unquoted). Existing file: use the exact sha256 returned by read. Never overwrite unrelated changes.",
            registry.registry["file_write"].schema,
            resolved_only,
            main=True,
            effect="write",
        )
    )
    argv_schema = {
        "type": "array",
        "items": {"type": "string"},
        "minItems": 1,
    }
    schema = object_schema(
        {
            "argv": argv_schema,
            "command": {"type": "string", "minLength": 1, "maxLength": 100000},
            "cwd": {"type": "string"},
            "timeout": {"type": "integer", "minimum": 0},
        }
    )
    schema["oneOf"] = [
        {"required": ["argv"], "not": {"required": ["command"]}},
        {"required": ["command"], "not": {"required": ["argv"]}},
    ]
    registry.add(
        Tool(
            "bash",
            "Execute Roami CLI argv discovered by tool_list, or shell commands in a prepared workspace. For Roami business actions use ['roami','agent','capability','call',NAME,'--input',JSON]. Registered read/write effects and receipts are enforced by runtime. General shell needs cwd inside allowed roots; no implicit code workspace is created.",
            schema,
            bash,
            main=True,
            effect="write",
            cancellation_stops_execution=True,
        )
    )
