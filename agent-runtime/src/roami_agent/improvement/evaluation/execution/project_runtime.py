"""A case-scoped Python test bridge, with no Docker socket inside the agent."""

import asyncio
import json
import os
import secrets
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

from roami_agent.improvement.domain.contracts import require
from roami_agent.improvement.evaluation.execution.project_snapshot import copy_project_snapshot
from roami_agent.improvement.integrations.artifact_files import private_json
from roami_agent.protocol.errors import DomainError


class ProjectRuntime:
    def __init__(self, socket, image_id, project, deadline):
        self.socket, self.image_id, self.project, self.deadline = (
            socket,
            image_id,
            project,
            deadline,
        )
        self.server = None
        self.clients = set()
        self.records = []
        self.lock = asyncio.Lock()

    async def __aenter__(self):
        self.server = await asyncio.start_unix_server(
            self.handle, path=str(self.socket), limit=64001
        )
        return self

    async def __aexit__(self, *error):
        self.server.close()
        await self.server.wait_closed()
        clients = list(self.clients)
        for client in clients:
            client.cancel()
        await asyncio.gather(*clients, return_exceptions=True)

    async def execute(self, argv):
        from roami_agent.improvement.evaluation.execution.containers import (
            docker_command,
            remove_container,
        )

        require(
            isinstance(argv, list)
            and 1 <= len(argv) <= 64
            and all(isinstance(a, str) and 0 < len(a) <= 2000 and "\x00" not in a for a in argv),
            "RSI_PROJECT_ARGUMENTS",
        )
        async with self.lock:
            require(len(self.records) < 32, "RSI_PROJECT_REQUEST_LIMIT")
            require(time.monotonic() < self.deadline, "RSI_TIME_BUDGET")
            record = {
                "id": "project-" + str(len(self.records) + 1),
                "state": "running",
                "tool_name": "project_python",
                "arguments_json": json.dumps({"argv": argv}),
            }
            self.records.append(record)
            started = time.monotonic()
            name = "roami-rsi-project-" + secrets.token_hex(8)
            created = False
            try:
                with tempfile.TemporaryDirectory(prefix="roami-rsi-project-") as directory:
                    snapshot = Path(directory) / "project"
                    record["source_snapshot"] = await asyncio.to_thread(
                        copy_project_snapshot, self.project, snapshot
                    )
                    require(time.monotonic() < self.deadline, "RSI_TIME_BUDGET")
                    script = 'exec 2>&1; source /opt/miniconda3/bin/activate testbed && cd /testbed && python "$@" 2>&1; code=$?; printf "\\nRSI_PROJECT_EXIT:%s\\n" "$code"; exit 0'
                    await docker_command(
                        "create",
                        "--name",
                        name,
                        "--label",
                        "roami.rsi=" + name,
                        "--network",
                        "none",
                        "--read-only",
                        "--cap-drop",
                        "ALL",
                        "--security-opt",
                        "no-new-privileges",
                        "--user",
                        f"{os.getuid()}:{os.getgid()}",
                        "--memory",
                        "2g",
                        "--cpus",
                        "2",
                        "--pids-limit",
                        "256",
                        "--tmpfs",
                        "/tmp:rw,exec,size=536870912,mode=1777",
                        "--mount",
                        f"type=bind,src={snapshot},dst=/testbed,readonly",
                        "--env",
                        "HOME=/tmp/home",
                        "--workdir",
                        "/testbed",
                        "--entrypoint",
                        "/bin/bash",
                        self.image_id,
                        "-c",
                        script,
                        "project-python",
                        *argv,
                    )
                    created = True
                    output = (
                        await docker_command(
                            "start",
                            "--attach",
                            name,
                            timeout=max(0.001, min(180, self.deadline - time.monotonic())),
                        )
                    ).decode(errors="replace")
                    body, marker = output.rsplit("\nRSI_PROJECT_EXIT:", 1)
                    exit_code = int(marker.strip())
                    record.update(
                        state="succeeded" if exit_code == 0 else "failed",
                        result_json=json.dumps({"exit_code": exit_code, "output": body}),
                    )
                    return {"exit_code": exit_code, "output": body[-20000:]}
            except asyncio.CancelledError:
                record["state"] = "unknown"
                record["result_json"] = json.dumps({"error": "RSI_PROJECT_INTERRUPTED"})
                raise
            except (DomainError, OSError, ValueError, TimeoutError) as error:
                record["state"] = "failed"
                record["result_json"] = json.dumps(
                    {
                        "error": error.code
                        if isinstance(error, DomainError)
                        else "RSI_PROJECT_RUNTIME_FAILED"
                    }
                )
                raise
            finally:
                if created:
                    await remove_container(name, name)
                record["elapsed_ms"] = (time.monotonic() - started) * 1000

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.clients.add(task)
        try:
            try:
                async with asyncio.timeout(10):
                    raw = await reader.readline()
                    require(len(raw) <= 64000, "RSI_PROJECT_ARGUMENTS")
                    request = json.loads(raw)
                result = await self.execute(request["argv"])
            except (DomainError, OSError, ValueError, KeyError, TypeError, TimeoutError) as error:
                result = {
                    "exit_code": 1,
                    "error": error.code
                    if isinstance(error, DomainError)
                    else "RSI_PROJECT_RUNTIME_FAILED",
                }
            writer.write(json.dumps(result).encode())
            await writer.drain()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            self.clients.discard(task)


@asynccontextmanager
async def project_runtime(case, directory, workspace, root, deadline):
    if case["judge"]["kind"] != "swe":
        yield None
        return
    from roami_agent.improvement.evaluation.benchmarks.swe_tasks import resolve_image

    image_id = await resolve_image(case["judge"]["image"])
    runtime = ProjectRuntime(
        Path(directory) / "project.sock", image_id, workspace / "project", deadline
    )
    try:
        async with runtime:
            yield runtime
    finally:
        private_json(
            root / "project-runtime-log.json",
            {"tool_calls": runtime.records, "traces": [], "image_id": image_id},
        )
