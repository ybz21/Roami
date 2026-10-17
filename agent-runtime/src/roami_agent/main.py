"""Launch only on a private Unix socket; Go resolves paths and registers the database."""

import argparse
import asyncio
import os
import socket
import stat
from pathlib import Path

import uvicorn

from .coding_executor import CodingExecutor
from .configuration import Settings
from .providers import ChatCompletions
from .runtime import Runtime
from .server import create_app
from .storage import Database


async def serve(args):
    settings = Settings.load(args.config)
    database = Database(args.database, args.data_root)
    await database.open()
    if args.initialize:
        await database.close()
        return
    provider = ChatCompletions(
        settings.endpoint, settings.model, settings.credentials(), timeout=settings.timeout_seconds
    )
    worker = (
        ChatCompletions(
            settings.endpoint,
            settings.worker_model,
            settings.credentials(),
            timeout=settings.timeout_seconds,
        )
        if settings.worker_model
        else provider
    )
    runtime = Runtime(
        database,
        provider,
        settings=settings,
        worker_model=worker,
        executor=CodingExecutor(database, settings),
    )
    try:
        args.socket.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(args.socket.parent, 0o700)
        os.umask(0o077)
        if args.socket.exists():
            metadata = args.socket.lstat()
            if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.geteuid():
                raise RuntimeError("AGENT_SOCKET_PATH_CONFLICT")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                try:
                    probe.connect(str(args.socket))
                except ConnectionRefusedError:
                    args.socket.unlink()
                else:
                    raise RuntimeError("AGENT_SOCKET_ALREADY_LISTENING")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as bound:
            bound.bind(str(args.socket))
            os.chmod(args.socket, 0o600)
            bound.listen(128)
            bound.setblocking(False)
            server = uvicorn.Server(
                uvicorn.Config(create_app(runtime), uds=str(args.socket), log_level="info")
            )
            await server.serve(sockets=[bound])
    finally:
        await runtime.close()
        await provider.close()
        if worker is not provider:
            await worker.close()
        await database.close()


def main():
    parser = argparse.ArgumentParser(
        description="Roami Agent private service; start via roami agent serve"
    )
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--socket", type=Path)
    parser.add_argument("--initialize", action="store_true")
    args = parser.parse_args()
    if not args.initialize and not args.socket:
        parser.error("--socket is required when serving")
    asyncio.run(serve(args))


if __name__ == "__main__":
    main()
