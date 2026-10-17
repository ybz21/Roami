"Composition root and lifecycle; domain services and adapters are assembled here."

import argparse
import asyncio
import logging
import os
import socket
import stat
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import uvicorn

from roami_agent.context.projection import Context
from roami_agent.context.prompt_builder import PromptBuilder
from roami_agent.conversation.mailbox import TurnMailbox
from roami_agent.conversation.service import ConversationService
from roami_agent.conversation.transcript import Conversations
from roami_agent.core.loop import AgentLoop
from roami_agent.dispatch.resource_leases import ResourceLeases
from roami_agent.dispatch.runner import TaskDispatcher
from roami_agent.dispatch.scheduler import Scheduler
from roami_agent.dispatch.tasks import Tasks
from roami_agent.executors.native import NativeExecutor
from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.executors.targets import TargetDirectory
from roami_agent.memory.jobs import MemoryJobs
from roami_agent.memory.records import Memories
from roami_agent.observability.prompt_manifests import PromptManifests
from roami_agent.protocol.errors import DomainError
from roami_agent.providers.chat_completions import ChatCompletions
from roami_agent.replies.notifications import Notifications
from roami_agent.server.configuration import Settings
from roami_agent.storage.artifact_store import ArtifactStore
from roami_agent.storage.database import Database
from roami_agent.storage.turn_journal import TurnJournal
from roami_agent.tools.artifacts import register_artifact_tools
from roami_agent.tools.gateway import ToolGateway
from roami_agent.tools.main_catalog import register_main_tools
from roami_agent.tools.mcp import MCPConnections, validate_servers
from roami_agent.tools.registry import Tools
from roami_agent.tools.worker_catalog import add_worker_tools

log = logging.getLogger(__name__)


class Runtime:
    def __init__(
        self,
        database: Database,
        model,
        *,
        settings=None,
        worker_model=None,
        memory_model=None,
        executor=None,
        verifier: Callable[[dict, dict], Awaitable[bool]] | None = None,
    ):
        self.db, self.model = database, model
        self.settings = settings or Settings()
        self.worker_model = worker_model or model
        self.executor, self.verifier = executor, verifier
        self.conversations = Conversations(database)
        self.artifacts = ArtifactStore(database, max_bytes=self.settings.artifact_max_bytes)
        self.resources = ResourceLeases(database)
        self.memory = Memories(database, self.settings.memory_timezone)
        self.memory_jobs = MemoryJobs(
            database, memory_model or self.worker_model, self.memory, self.memory.daily
        )
        self.notifications = Notifications(database)
        self.context = Context(database, model, input_budget=self.settings.input_budget)
        self.tasks = Tasks(database, self.conversations, max_depth=self.settings.max_depth)
        self.tools = Tools()
        self.active = {}
        self.turn_tasks = {}
        self.wakeup = asyncio.Event()
        self.stopping = False
        self.supervisor = None
        self.external_monitor = None
        register_main_tools(self.tools, self.tasks, self.memory, TargetDirectory(self.settings))
        add_worker_tools(self.tools, self.settings, self.artifacts)
        register_artifact_tools(self.tools, self.artifacts)
        self.mcp = MCPConnections(self.tools, self.settings.mcp_servers, self.artifacts)

        self.mailbox = TurnMailbox(database)
        self.journal = TurnJournal(database)
        self.gateway = ToolGateway(database, self.tools, self.wakeup)
        self.manifests = PromptManifests(database)
        self.dispatch = TaskDispatcher(
            database,
            self.tasks,
            executor,
            verifier,
            NativeExecutor(
                lambda *args, **kwargs: self.loop.run(*args, **kwargs), database, self.settings
            ),
            self.wakeup,
            self.active,
        )
        self.loop = AgentLoop(
            model,
            self.worker_model,
            self.settings,
            PromptBuilder(database, self.context, self.settings),
            self.journal,
            self.tools,
            self.manifests,
            self.dispatch.charge_budget,
            self.turn_tasks,
            time.monotonic,
            self.gateway,
        )
        self.scheduler = Scheduler(
            database,
            self.settings,
            self.context,
            self.dispatch,
            self.mailbox,
            self.loop.run,
            self.wakeup,
            self.active,
            self.memory_jobs,
        )
        self.chat = ConversationService(
            database,
            self.conversations,
            self.context,
            self.tasks,
            model,
            self.wakeup,
            self.turn_tasks,
        )

    async def start(self):
        await self.conversations.recover()
        await self.memory_jobs.recover()
        await self.resources.recover()
        await self.dispatch.recover()
        self.supervisor = asyncio.create_task(self.scheduler.run(), name="roami-agent-supervisor")
        if self.executor and getattr(self.executor, "can_reconcile", False):
            self.external_monitor = asyncio.create_task(self._monitor_external())
        self.wakeup.set()

    async def _monitor_external(self):
        while not self.stopping:
            try:
                expired = await self.executor.poll(self.tasks)
                for task, run in expired or ():
                    await self.dispatch.complete(
                        task,
                        run,
                        {
                            "state": "failed",
                            "summary": "EXECUTION_DEADLINE_STOP_UNCONFIRMED",
                            "outcomeKnown": False,
                            "retryable": False,
                        },
                        "interrupted",
                        unknown=True,
                    )
                self.wakeup.set()
            except (DomainError, OSError, TimeoutError):
                log.exception("External executor observation failed")
            await asyncio.sleep(1)

    async def close(self):
        self.stopping = True
        self.scheduler.stopping = True
        self.wakeup.set()
        if self.supervisor:
            await self.supervisor
        if self.external_monitor:
            self.external_monitor.cancel()
            await asyncio.gather(self.external_monitor, return_exceptions=True)
        running = [item["handle"] for item in self.active.values()]
        for handle in running:
            handle.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        await self.mcp.close()
        await self.artifacts.close()


async def serve(args):
    from roami_agent.server.http import create_app

    settings = Settings.load(args.config)
    validate_servers(settings.mcp_servers)
    database = Database(args.database, args.data_root)
    await database.open()
    if args.initialize:
        await database.close()
        return
    provider = ChatCompletions(
        settings.endpoint,
        settings.model,
        settings.credentials(),
        timeout=settings.timeout_seconds,
        max_retries=settings.model_retries,
        capabilities=settings.model_capabilities,
        cache=settings.model_cache,
    )
    worker = (
        ChatCompletions(
            settings.endpoint,
            settings.worker_model,
            settings.credentials(),
            timeout=settings.timeout_seconds,
            max_retries=settings.model_retries,
            capabilities=settings.model_capabilities,
            cache=settings.model_cache,
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
