import asyncio
import json

from jsonschema import Draft202012Validator, ValidationError

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.serialization import encoded
from roami_agent.protocol.tools import Tool


class Tools:
    def __init__(self):
        self.registry: dict[str, Tool] = {}
        self.disabled_tools: set[str] = set()
        self.disabled_skills: set[str] = set()
        self.skills: dict[str, dict] = {}

    def add(self, tool):
        if tool.name in self.registry:
            raise DomainError("DUPLICATE_TOOL")
        Draft202012Validator.check_schema(tool.schema)
        self.registry[tool.name] = tool

    def catalog(self, role="main"):
        return [
            t.wire()
            for t in self.registry.values()
            if t.name not in self.disabled_tools and (role != "main" or t.main)
        ]

    def validate(self, call, role):
        name = call["function"]["name"]
        tool = self.registry.get(name)
        if name in self.disabled_tools:
            raise DomainError("TOOL_DISABLED")
        if not tool or (role == "main" and not tool.main):
            raise DomainError("TOOL_UNAVAILABLE")
        try:
            args = json.loads(call["function"]["arguments"])
            Draft202012Validator(tool.schema).validate(args)
        except (ValueError, ValidationError) as exc:
            raise DomainError("INVALID_TOOL_ARGUMENTS") from exc
        return tool, args

    async def invoke(self, call, role, binding):
        tool, args = self.validate(call, role)
        async with asyncio.timeout(60):
            value = await tool.handler(args, binding)
        if len(encoded(value).encode()) > 128_000:
            raise DomainError("TOOL_OUTPUT_LIMIT")
        return value
