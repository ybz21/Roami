import hashlib

import httpx

from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.tools.shell import register_shell


def add_worker_tools(registry, settings):
    register_shell(registry, settings)

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
