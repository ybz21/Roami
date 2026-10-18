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
from roami_agent.context.vision_inputs import VisionInputs
from roami_agent.conversation.mailbox import TurnMailbox
from roami_agent.conversation.service import ConversationService
from roami_agent.conversation.transcript import Conversations
from roami_agent.core.loop import AgentLoop
from roami_agent.dispatch.reminders import Reminders
from roami_agent.dispatch.resource_controls import ResourceControls
from roami_agent.dispatch.resource_leases import ResourceLeases
from roami_agent.dispatch.runner import TaskDispatcher
from roami_agent.dispatch.scheduler import Scheduler
from roami_agent.dispatch.tasks import Tasks
from roami_agent.executors.browser_driver import BrowserDriver
from roami_agent.executors.desktop_driver import DesktopDriver
from roami_agent.executors.native import NativeExecutor
from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.executors.targets import TargetDirectory
from roami_agent.memory.jobs import MemoryJobs
from roami_agent.memory.records import Memories
from roami_agent.observability.prompt_manifests import PromptManifests
from roami_agent.protocol.errors import DomainError
from roami_agent.providers.chat_completions import ChatCompletions
from roami_agent.replies.delivery_outbox import DeliveryOutbox
from roami_agent.replies.notification_policy import NotificationPolicy
from roami_agent.replies.notifications import Notifications
from roami_agent.replies.proactive_jobs import ProactiveJobs
from roami_agent.server.configuration import Settings
from roami_agent.storage.artifact_store import ArtifactStore
from roami_agent.storage.database import Database
from roami_agent.storage.turn_journal import TurnJournal
from roami_agent.storage.workspace_files import WorkspaceFiles
from roami_agent.tools.artifacts import register_artifact_tools
from roami_agent.tools.browser import register_browser_tools
from roami_agent.tools.computer import register_computer_tools
from roami_agent.tools.files import register_file_tools
from roami_agent.tools.gateway import ToolGateway
from roami_agent.tools.main_catalog import register_main_tools
from roami_agent.tools.mcp import MCPConnections, validate_servers
from roami_agent.tools.registry import Tools
from roami_agent.tools.reminders import register_reminder_tools
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
        self.tasks = Tasks(database, self.conversations, max_depth=self.settings.max_depth)
        self.artifacts = ArtifactStore(database, max_bytes=self.settings.artifact_max_bytes)
        self.files = WorkspaceFiles(self.settings)
        self.resources = ResourceLeases(database)
        self.controls = ResourceControls(database, self.resources)
        self.memory = Memories(
            database,
            self.settings.memory_timezone,
            cancel_forgotten=self.tasks.cancel_forgotten_in_transaction,
        )
        self.memory_jobs = MemoryJobs(
            database,
            memory_model or self.worker_model,
            self.memory,
            self.memory.daily,
            artifacts=self.artifacts,
        )
        self.notifications = Notifications(database)
        self.notification_policy = NotificationPolicy(
            database, timezone_name=self.settings.memory_timezone
        )
        self.reminders = Reminders(database)
        self.deliveries = DeliveryOutbox(database, self.notification_policy)
        self.proactive = ProactiveJobs(
            database,
            self.worker_model,
            self.notification_policy,
            daily_budget=self.settings.proactive_daily_budget,
            timeout=self.settings.proactive_timeout_seconds,
        )
        self.context = Context(database, model, input_budget=self.settings.input_budget)
        self.tools = Tools()
        self.active = {}
        self.turn_tasks = {}
        self.wakeup = asyncio.Event()
        self.stopping = False
        self.supervisor = None
        self.external_monitor = None
        self.browser_monitor = None
        self.desktop_monitor = None
        self.control_monitor = None
        self.reminder_monitor = None
        self.proactive_monitor = None
        register_main_tools(self.tools, self.tasks, self.memory, TargetDirectory(self.settings))
        register_reminder_tools(
            self.tools, self.reminders, self.settings.memory_timezone, self.notification_policy
        )
        add_worker_tools(self.tools, self.settings, self.artifacts)
        register_file_tools(self.tools, self.files)
        register_artifact_tools(self.tools, self.artifacts)
        self.mcp = MCPConnections(self.tools, self.settings.mcp_servers, self.artifacts)
        self.browser = BrowserDriver(database, self.settings, self.resources, self.artifacts)
        if self.browser.config.get("enabled"):
            register_browser_tools(self.tools, self.browser)
        self.desktop = DesktopDriver(database, self.settings, self.resources, self.artifacts)
        if self.desktop.config["enabled"]:
            register_computer_tools(self.tools, self.desktop)

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
                lambda *args, **kwargs: self.loop.run(*args, **kwargs),
                database,
                self.settings,
                resources=self.resources
                if self.browser.config.get("enabled") or self.desktop.config["enabled"]
                else None,
                artifacts=self.artifacts,
            ),
            self.wakeup,
            self.active,
        )
        self.loop = AgentLoop(
            model,
            self.worker_model,
            self.settings,
            PromptBuilder(
                database,
                self.context,
                self.settings,
                vision=VisionInputs(database, self.artifacts)
                if self.settings.route("worker").capabilities.get("images") is True
                else None,
            ),
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
        if self.settings.proactive_enabled:
            await self.proactive.recover()
        self.supervisor = asyncio.create_task(self.scheduler.run(), name="roami-agent-supervisor")
        if self.executor and getattr(self.executor, "can_reconcile", False):
            self.external_monitor = asyncio.create_task(self._monitor_external())
        self.browser_monitor = asyncio.create_task(self._monitor_browser())
        self.desktop_monitor = asyncio.create_task(self._monitor_desktop())
        self.control_monitor = asyncio.create_task(self._monitor_controls())
        self.reminder_monitor = asyncio.create_task(self._monitor_reminders())
        if self.settings.proactive_enabled:
            self.proactive_monitor = asyncio.create_task(self._monitor_proactive())
        self.wakeup.set()

    async def _monitor_reminders(self):
        while not self.stopping:
            try:
                await self.reminders.tick()
            except Exception:
                log.exception("Reminder scheduling failed")
            await asyncio.sleep(1)

    async def _monitor_proactive(self):
        while not self.stopping:
            try:
                await self.proactive.tick()
            except Exception:
                log.exception("Proactive evaluation failed")
            await asyncio.sleep(1)

    async def _monitor_browser(self):
        while not self.stopping:
            try:
                await self.browser.reconcile()
            except (DomainError, OSError, TimeoutError):
                log.exception("Browser operation observation failed")
            await asyncio.sleep(1)

    async def _monitor_desktop(self):
        while not self.stopping:
            try:
                await self.desktop.reconcile()
            except (DomainError, OSError, TimeoutError):
                log.exception("Desktop operation observation failed")
            await asyncio.sleep(1)

    async def _monitor_controls(self):
        while not self.stopping:
            try:
                await self.controls.release_ready()
            except (DomainError, OSError):
                log.exception("Resource takeover observation failed")
            await asyncio.sleep(0.2)

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
        if self.reminder_monitor:
            self.reminder_monitor.cancel()
            await asyncio.gather(self.reminder_monitor, return_exceptions=True)
        if self.proactive_monitor:
            self.proactive_monitor.cancel()
            await asyncio.gather(self.proactive_monitor, return_exceptions=True)
        if self.browser_monitor:
            self.browser_monitor.cancel()
            await asyncio.gather(self.browser_monitor, return_exceptions=True)
        if self.desktop_monitor:
            self.desktop_monitor.cancel()
            await asyncio.gather(self.desktop_monitor, return_exceptions=True)
        if self.control_monitor:
            self.control_monitor.cancel()
            await asyncio.gather(self.control_monitor, return_exceptions=True)
        running = [item["handle"] for item in self.active.values()]
        for handle in running:
            handle.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        await self.mcp.close()
        await self.desktop.close()
        await self.files.close()
        await self.artifacts.close()


def configured_provider(settings, role, *, client=None):
    route = settings.route(role)
    return ChatCompletions(
        route.endpoint,
        route.name,
        settings.credentials(role),
        timeout=route.timeout_seconds,
        max_retries=route.max_retries,
        capabilities=route.capabilities,
        cache=route.cache,
        parameters=route.parameters,
        client=client,
    )


async def serve(args):
    from roami_agent.server.http import create_app

    settings = Settings.load(args.config)
    validate_servers(settings.mcp_servers)
    database = Database(args.database, args.data_root)
    await database.open()
    if args.initialize:
        await database.close()
        return

    provider = configured_provider(settings, "main")
    worker = (
        provider
        if settings.route("main") == settings.route("worker")
        else configured_provider(settings, "worker")
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
