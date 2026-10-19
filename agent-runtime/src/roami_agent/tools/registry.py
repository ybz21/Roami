import asyncio
import json
from copy import deepcopy

from jsonschema import Draft202012Validator, ValidationError

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.research import RESEARCH_TOOLS, research_call_allowed
from roami_agent.protocol.serialization import encoded
from roami_agent.protocol.tools import Tool


class Tools:
    def __init__(self):
        self.registry: dict[str, Tool] = {}
        self.disabled_tools: set[str] = set()
        self.disabled_skills: set[str] = set()
        self.skills: dict[str, dict] = {}
        self.directory = None

    def add(self, tool):
        if tool.name in self.registry:
            raise DomainError("DUPLICATE_TOOL")
        Draft202012Validator.check_schema(tool.schema)
        self.registry[tool.name] = tool

    def catalog(self, role="main"):
        result = []
        for tool in self.registry.values():
            if self.directory:
                from roami_agent.tools.foundations import (
                    FOUNDATIONS,
                    RESEARCH_FOUNDATIONS,
                    WORKER_FOUNDATIONS,
                )

                names = (
                    RESEARCH_FOUNDATIONS
                    if role == "research"
                    else WORKER_FOUNDATIONS
                    if role != "main"
                    else FOUNDATIONS
                )
                if tool.name not in names:
                    continue
            if (
                tool.name in self.disabled_tools
                or role == "main"
                and not tool.main
                or role == "research"
                and not self.directory
                and tool.name not in RESEARCH_TOOLS
            ):
                continue
            wire = tool.wire()
            if role == "main" and self.directory and tool.name == "delegate":
                wire = deepcopy(wire)
                wire["function"]["parameters"]["required"] = ["goal", "routing"]
            if role == "research":
                wire = deepcopy(wire)
                parameters = wire["function"]["parameters"]
                if tool.name == "browser_act":
                    parameters["properties"]["kind"]["enum"] = ["goto"]
                    parameters["required"] = ["observationId", "kind", "url"]
                elif tool.name == "browser_open":
                    parameters["properties"].pop("targetId", None)
                elif tool.name == "skill_read":
                    parameters["properties"]["name"]["enum"] = ["web-research"]
            result.append(wire)
        return result

    def validate(self, call, role):
        name = call["function"]["name"]
        tool = self.registry.get(name)
        if name in self.disabled_tools:
            raise DomainError("TOOL_DISABLED")
        if self.directory:
            from roami_agent.tools.foundations import FOUNDATIONS

            parent = {
                "skill_read": "read",
                "file_read": "read",
                "file_patch": "edit",
                "file_write": "write",
                "web_research": "delegate",
            }.get(name, "bash" if name not in FOUNDATIONS else name)
            if parent in self.disabled_tools:
                raise DomainError("TOOL_DISABLED")
        if not tool or (role == "main" and not tool.main):
            raise DomainError("TOOL_UNAVAILABLE")
        try:
            args = json.loads(call["function"]["arguments"])
            Draft202012Validator(tool.schema).validate(args)
        except (ValueError, ValidationError) as exc:
            raise DomainError("INVALID_TOOL_ARGUMENTS") from exc
        if self.directory:
            tool, args = self.directory.resolve(tool, args, role)
            if tool.name in self.disabled_tools:
                raise DomainError("TOOL_DISABLED")
            try:
                Draft202012Validator(tool.schema).validate(args)
            except ValidationError as exc:
                raise DomainError("INVALID_TOOL_ARGUMENTS") from exc
        if (
            role == "research"
            and tool.name != "tool_list"
            and not research_call_allowed(tool.name, args)
        ):
            raise DomainError("TOOL_UNAVAILABLE")
        return tool, args

    async def invoke(self, call, role, binding):
        tool, args = self.validate(call, role)
        async with asyncio.timeout(60):
            value = await tool.handler(args, dict(binding, role=role))
        if len(encoded(value).encode()) > 128_000:
            raise DomainError("TOOL_OUTPUT_LIMIT")
        return value
