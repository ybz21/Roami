"Bounded process-group execution for tools and the external Roami CLI boundary."

import asyncio
import os
import signal
from pathlib import Path

from roami_agent.protocol.errors import DomainError


async def execute(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout=60,
    input_data=None,
    env: dict | None = None,
    max_bytes=128_000,
):
    if cwd is not None and env is None:
        bindings = {
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_OBJECT_DIRECTORY",
            "GIT_COMMON_DIR",
            "GIT_PREFIX",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_NAMESPACE",
            "GIT_IMPLICIT_WORK_TREE",
            "GIT_SHALLOW_FILE",
            "GIT_GRAFT_FILE",
        }
        env = {name: value for name, value in os.environ.items() if name not in bindings}
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        env=env,
        start_new_session=True,
        stdin=asyncio.subprocess.PIPE if input_data is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def collect(stream):
        parts, size = [], 0
        while chunk := await stream.read(8192):
            size += len(chunk)
            if size > max_bytes:
                raise DomainError("PROCESS_OUTPUT_LIMIT")
            parts.append(chunk)
        return b"".join(parts).decode("utf-8", errors="replace")

    async def exchange():
        if input_data is not None:
            try:
                process.stdin.write(input_data)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()
        stdout, stderr, code = await asyncio.gather(
            collect(process.stdout), collect(process.stderr), process.wait()
        )
        return {"stdout": stdout, "stderr": stderr, "exitCode": code}

    try:
        async with asyncio.timeout(timeout):
            return await exchange()
    finally:
        # The wrapper may exit while descendants still hold a pipe or run a write tool.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
