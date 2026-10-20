"Cancellable process-group execution with optional file-backed output."

import asyncio
import os
import signal
from pathlib import Path

from roami_agent.protocol.errors import DomainError


async def execute(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout=None,
    input_data=None,
    env: dict | None = None,
    max_bytes=None,
    raw_output=False,
    excluded_env=(),
    output_directory=None,
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
    if excluded_env:
        env = {
            name: value
            for name, value in (os.environ if env is None else env).items()
            if name not in excluded_env
        }
    output_files = {}
    if output_directory is not None:
        try:
            for name in ("stdout", "stderr"):
                path = Path(output_directory) / name
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                output_files[name] = os.fdopen(descriptor, "wb")
        except BaseException:
            for file in output_files.values():
                file.close()
            raise
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=env,
            start_new_session=True,
            stdin=asyncio.subprocess.PIPE if input_data is not None else asyncio.subprocess.DEVNULL,
            stdout=output_files.get("stdout", asyncio.subprocess.PIPE),
            stderr=output_files.get("stderr", asyncio.subprocess.PIPE),
        )
    finally:
        for file in output_files.values():
            file.close()

    async def collect(stream):
        parts, size = [], 0
        while chunk := await stream.read(8192):
            size += len(chunk)
            if max_bytes is not None and size > max_bytes:
                raise DomainError("PROCESS_OUTPUT_LIMIT")
            parts.append(chunk)
        body = b"".join(parts)
        return body if raw_output else body.decode("utf-8", errors="replace")

    async def exchange():
        if input_data is not None:
            try:
                process.stdin.write(input_data)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()
        if output_directory is not None:
            code = await process.wait()
            return {
                "stdout": Path(output_directory) / "stdout",
                "stderr": Path(output_directory) / "stderr",
                "exitCode": code,
            }
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
