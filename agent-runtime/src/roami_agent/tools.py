"""Typed tool registry and scoped worker tools; the Main catalog stays small."""

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator, ValidationError

from .process import execute
from .storage import DomainError, encoded


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    handler: Callable[[dict, dict], Awaitable[object]]
    effect: str = "read"
    main: bool = False

    def wire(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            },
        }


def object_schema(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


class Tools:
    def __init__(self):
        self.registry: dict[str, Tool] = {}

    def add(self, tool):
        if tool.name in self.registry:
            raise DomainError("DUPLICATE_TOOL")
        Draft202012Validator.check_schema(tool.schema)
        self.registry[tool.name] = tool

    def catalog(self, role="main"):
        return [t.wire() for t in self.registry.values() if role != "main" or t.main]

    def validate(self, call, role):
        name = call["function"]["name"]
        tool = self.registry.get(name)
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


def add_worker_tools(registry, settings):
    if settings.shell_roots:

        async def shell(args, binding):
            cwd = Path(args["cwd"]).expanduser().resolve()
            if not any(cwd == root or root in cwd.parents for root in settings.shell_roots):
                raise DomainError("WORKSPACE_OUTSIDE_CONFIGURED_ROOTS")
            return await execute(args["argv"], cwd=cwd, timeout=min(args.get("timeout", 60), 60))

        registry.add(
            Tool(
                "shell",
                "Execute an argv in a configured workspace; no implicit shell.",
                object_schema(
                    {
                        "argv": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 100,
                        },
                        "cwd": {"type": "string"},
                        "timeout": {"type": "integer", "minimum": 1, "maximum": 60},
                    },
                    ["argv", "cwd"],
                ),
                shell,
                effect="write",
            )
        )

    for name, config in settings.http_tools.items():

        async def request(args, binding, config=config):
            headers = dict(config.get("headers", {}))
            if config.get("key_env"):
                import os

                headers["Authorization"] = "Bearer " + os.environ.get(config["key_env"], "")
            async with (
                httpx.AsyncClient(timeout=30, follow_redirects=False) as client,
                client.stream(
                    config.get("method", "GET"),
                    config["url"],
                    headers=headers,
                    params=args if config.get("method", "GET") == "GET" else None,
                    json=args if config.get("method", "GET") != "GET" else None,
                ) as response,
            ):
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 64_000:
                        raise DomainError("HTTP_OUTPUT_LIMIT")
                return {"status": response.status_code, "body": data.decode(errors="replace")}

        registry.add(
            Tool(
                "http_" + name,
                config.get("description", name),
                config.get("schema", object_schema({})),
                request,
                effect="read" if config.get("method", "GET") in {"GET", "HEAD"} else "write",
            )
        )

    skills = {}
    for root in settings.skill_roots:
        if not root.is_dir():
            continue
        for path in root.glob("*/SKILL.md"):
            resolved = path.resolve()
            if root not in resolved.parents or resolved.stat().st_size > 64_000:
                continue
            text = resolved.read_text()
            name = path.parent.name
            if name in skills:
                raise DomainError("DUPLICATE_SKILL")
            skills[name] = {"text": text, "version": hashlib.sha256(text.encode()).hexdigest()}
    if skills:

        async def skill(args, binding):
            return skills[args["name"]]

        registry.add(
            Tool(
                "skill_read",
                "Load a skill only when needed: " + ", ".join(skills),
                object_schema({"name": {"type": "string", "enum": list(skills)}}, ["name"]),
                skill,
            )
        )
