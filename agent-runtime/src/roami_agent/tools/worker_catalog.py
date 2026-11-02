import re
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from roami_agent.protocol.tools import Tool, object_schema
from roami_agent.tools.host_processes import register_host_processes
from roami_agent.tools.shell import register_shell
from roami_agent.tools.skills import register_skills


def add_worker_tools(registry, settings, artifacts=None):
    register_shell(registry, settings, artifacts)
    register_host_processes(registry)

    for name, config in settings.http_tools.items():

        async def request(args, binding, config=config):
            headers = dict(config.get("headers", {}))
            if config.get("key_env"):
                import os

                headers["Authorization"] = "Bearer " + os.environ.get(config["key_env"], "")
            async with (
                httpx.AsyncClient(
                    timeout=httpx.Timeout(config.get("timeout_seconds") or None, connect=10),
                    follow_redirects=False,
                ) as client,
                client.stream(
                    config.get("method", "GET"),
                    config["url"],
                    headers=headers,
                    params=args if config.get("method", "GET") == "GET" else None,
                    json=args if config.get("method", "GET") != "GET" else None,
                ) as response,
            ):
                if artifacts is None:
                    data = await response.aread()
                    return {"status": response.status_code, "body": data.decode(errors="replace")}
                with TemporaryDirectory(
                    prefix=".http-output-", dir=artifacts.data_root
                ) as directory:
                    path = Path(directory) / "response"
                    with path.open("wb") as output:
                        async for chunk in response.aiter_bytes():
                            output.write(chunk)
                    size = path.stat().st_size
                    with path.open("rb") as source:
                        preview = source.read(64000)
                    if size <= 64000:
                        return {
                            "status": response.status_code,
                            "body": preview.decode(errors="replace"),
                        }
                    mime = (
                        response.headers.get("content-type", "text/plain").split(";", 1)[0].strip()
                    )
                    if not re.fullmatch(r"[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+", mime):
                        mime = "application/octet-stream"
                    reference = await artifacts.put_file(
                        binding["owner"],
                        path,
                        mime_type=mime,
                        name="http-response.bin",
                        task_id=binding.get("taskId"),
                        message_id=binding.get("assistantMessageId"),
                        metadata={"source": "http", "status": response.status_code},
                    )
                    return {
                        "status": response.status_code,
                        "body": preview[:4000].decode(errors="replace"),
                        "artifactRefs": [reference],
                        "outputExternalized": True,
                    }

        registry.add(
            Tool(
                "http_" + name,
                config.get("description", name),
                config.get("schema", object_schema({})),
                request,
                effect="read" if config.get("method", "GET") in {"GET", "HEAD"} else "write",
                source="external",
            )
        )

    register_skills(registry, settings)
