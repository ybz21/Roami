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

from roami_agent.context.chat_images import ChatImages
from roami_agent.context.document_intake import TaskDocumentIntake
from roami_agent.context.projection import Context
from roami_agent.context.prompt_builder import PromptBuilder
from roami_agent.context.token_estimate import request_context
from roami_agent.context.vision_inputs import VisionInputs
from roami_agent.conversation.attachments import Attachments
from roami_agent.conversation.mailbox import TurnMailbox
from roami_agent.conversation.service import ConversationService
from roami_agent.conversation.session_dispatches import SessionDispatches
from roami_agent.conversation.transcript import Conversations
from roami_agent.core.loop import AgentLoop
from roami_agent.dispatch.daily_briefs import DailyBriefs
from roami_agent.dispatch.reminders import Reminders
from roami_agent.dispatch.resource_controls import ResourceControls
from roami_agent.dispatch.resource_leases import ResourceLeases
from roami_agent.dispatch.routing import TaskRouter
from roami_agent.dispatch.runner import TaskDispatcher
from roami_agent.dispatch.scheduler import Scheduler
from roami_agent.dispatch.task_sessions import TaskSessions
from roami_agent.dispatch.task_workspace_cleanup import TaskWorkspaceCleanup
from roami_agent.dispatch.tasks import Tasks
from roami_agent.executors.browser_driver import BrowserDriver
from roami_agent.executors.desktop_driver import DesktopDriver
from roami_agent.executors.native import NativeExecutor
from roami_agent.executors.native_reconciliation import NativeWorkspaceReconciliation
from roami_agent.executors.roami_cli import CodingExecutor
from roami_agent.executors.targets import TargetDirectory
from roami_agent.improvement.domain.policy import BOUNDS
from roami_agent.improvement.service import ImprovementStatus
from roami_agent.memory.jobs import MemoryJobs
from roami_agent.memory.records import Memories
from roami_agent.observability.execution_debug import ExecutionDebug
from roami_agent.observability.execution_traces import ExecutionTraces, origin_turn
from roami_agent.observability.prompt_manifests import PromptManifests
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.improvement import policy_binding
from roami_agent.providers.factory import configured_provider
from roami_agent.replies.delivery_outbox import DeliveryOutbox
from roami_agent.replies.notification_policy import NotificationPolicy
from roami_agent.replies.notifications import Notifications
from roami_agent.replies.proactive_jobs import ProactiveJobs
from roami_agent.server.capability_imports import CapabilityImports
from roami_agent.server.capability_markets import CapabilityMarkets
from roami_agent.server.capability_settings import CapabilitySettings
from roami_agent.server.configuration import Settings
from roami_agent.server.model_settings import ModelSettings, RuntimeSettings, load_model_settings
from roami_agent.storage.artifact_retention import ArtifactRetention
from roami_agent.storage.artifact_store import ArtifactStore
from roami_agent.storage.database import Database
from roami_agent.storage.native_sessions import NativeSessions
from roami_agent.storage.task_deliverables import TaskDeliverables
from roami_agent.storage.turn_journal import TurnJournal
from roami_agent.storage.workspace_files import WorkspaceFiles
from roami_agent.tools.artifacts import register_artifact_tools
from roami_agent.tools.browser import register_browser_tools
from roami_agent.tools.cli_commands import CLICommands
from roami_agent.tools.computer import register_computer_tools
from roami_agent.tools.files import register_file_tools
from roami_agent.tools.foundations import register_foundations
from roami_agent.tools.gateway import ToolGateway
from roami_agent.tools.main_catalog import register_main_tools
from roami_agent.tools.market_commands import register_market_commands
from roami_agent.tools.mcp import MCPConnections, validate_servers
from roami_agent.tools.mcp_broker import MCPBroker, node_socket
from roami_agent.tools.professional_capabilities import ProfessionalCapabilities
from roami_agent.tools.registry import Tools
from roami_agent.tools.reminders import register_reminder_tools
from roami_agent.tools.web_research import register_research_tools
from roami_agent.tools.worker_catalog import add_worker_tools
from roami_agent.tools.workspace_images import WorkspaceImageReads

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
        development_rsi=False,
    ):
        self.db, self.model = database, model
        self.settings = RuntimeSettings(settings or Settings())
        self.reconfiguring = False
        self.memory_uses_worker = memory_model is None
        self.worker_model = worker_model or model
        self.executor, self.verifier = executor, verifier
        self.conversations = Conversations(database)
        self.tasks = Tasks(
            database,
            self.conversations,
            max_depth=self.settings.max_depth,
        )
        self.artifacts = ArtifactStore(database, max_bytes=self.settings.artifact_max_bytes)
        self.tasks.deliverables = TaskDeliverables(self.artifacts)
        if isinstance(self.executor, CodingExecutor):
            self.executor.artifacts = self.artifacts
        self.attachments = Attachments(database, self.artifacts)
        self.artifact_retention = ArtifactRetention(
            self.artifacts,
            grace_seconds=self.settings.artifact_gc_grace_seconds,
            interval_seconds=self.settings.artifact_gc_interval_seconds,
        )
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
            timeout_seconds=lambda: self.settings.route("worker").timeout_seconds,
        )
        self.notifications = Notifications(database)
        self.notification_policy = NotificationPolicy(
            database, timezone_name=self.settings.memory_timezone
        )
        self.reminders = Reminders(database)
        self.briefs = DailyBriefs(
            database,
            self.worker_model,
            timeout=self.settings.brief_timeout_seconds,
        )
        self.deliveries = DeliveryOutbox(database, self.notification_policy)
        self.proactive = ProactiveJobs(
            database,
            self.worker_model,
            self.notification_policy,
            timeout=self.settings.proactive_timeout_seconds,
        )
        self.context = Context(
            database,
            model,
            keep_recent_tokens=self.settings.keep_recent_tokens,
        )
        self.tools = Tools(self.artifacts)
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
        self.brief_monitor = None
        self.artifact_monitor = None
        self.native_reconciliation_monitor = None
        self.native_session_monitor = None
        self.native_sessions = NativeSessions(database)
        self.native_reconciliation = NativeWorkspaceReconciliation(
            database, self.settings, resources=self.resources
        )
        self.session_dispatches = SessionDispatches(database, self.settings)
        targets = TargetDirectory(self.settings, self.session_dispatches)
        register_main_tools(
            self.tools,
            self.tasks,
            self.memory,
            targets,
            TaskRouter(database, targets, self.settings, self.memory),
        )
        register_reminder_tools(
            self.tools,
            self.reminders,
            self.settings.memory_timezone,
            self.notification_policy,
            self.briefs,
        )
        add_worker_tools(self.tools, self.settings, self.artifacts)
        register_file_tools(
            self.tools, self.files, images=WorkspaceImageReads(self.files, self.artifacts)
        )
        register_artifact_tools(self.tools, self.artifacts)
        mcp_socket = node_socket(database.data_root)
        self.mcp = MCPConnections(
            self.tools,
            self.settings.mcp_servers,
            self.artifacts,
            broker=MCPBroker(Path(mcp_socket), data_root=database.data_root)
            if mcp_socket
            else None,
        )
        self.browser = BrowserDriver(database, self.settings, self.resources, self.artifacts)
        if self.browser.config.get("enabled"):
            register_browser_tools(self.tools, self.browser)
        self.desktop = DesktopDriver(database, self.settings, self.resources, self.artifacts)
        if self.desktop.config["enabled"]:
            register_computer_tools(self.tools, self.desktop)

        register_research_tools(self.tools, self.tasks)
        register_foundations(self.tools, self.settings)
        self.document_intake = TaskDocumentIntake(self.files, self.tools)

        self.context.request_context = lambda: request_context(
            self.settings, self.settings.main_instructions, self.tools.catalog("main")
        )

        self.mailbox = TurnMailbox(database)
        self.journal = TurnJournal(database)
        self.gateway = ToolGateway(database, self.tools, self.wakeup)
        self.cli_commands = CLICommands(database, self.tools, self.journal)
        self.manifests = PromptManifests(database)
        self.traces = ExecutionTraces(database)
        self.improvement = ImprovementStatus(database.data_root) if development_rsi else None
        self.debug = ExecutionDebug(database, self.context, self.settings, self.traces)
        self.dispatch = TaskDispatcher(
            database,
            self.tasks,
            executor,
            verifier,
            NativeExecutor(
                lambda *args, **kwargs: self.run_turn(*args, **kwargs),
                database,
                self.settings,
                resources=self.resources
                if self.browser.config.get("enabled") or self.desktop.config["enabled"]
                else None,
                artifacts=self.artifacts,
                documents=self.document_intake,
            ),
            self.wakeup,
            self.active,
        )
        self.task_sessions = TaskSessions(
            database,
            self.executor,
            self.dispatch.confirm,
            cleanup=TaskWorkspaceCleanup(database, self.settings, self.tasks),
        )
        self.loop = AgentLoop(
            model,
            self.worker_model,
            self.settings,
            PromptBuilder(
                database,
                self.context,
                self.settings,
                memory=self.memory,
                documents=self.document_intake,
                chat_images=ChatImages(database, self.artifacts, self.settings),
                vision=VisionInputs(database, self.artifacts, self.settings)
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
            self.run_turn,
            self.wakeup,
            self.active,
            self.memory_jobs,
            task_sessions=self.task_sessions,
        )
        self.chat = ConversationService(
            database,
            self.conversations,
            self.context,
            self.tasks,
            model,
            self.wakeup,
            self.turn_tasks,
            self.loop.preempt,
        )
        self.model_settings = ModelSettings(self, configured_provider)
        if self.improvement is not None:
            self.improvement.ledger.shared_daily_limit = True
            self.improvement.provider_factory = self.improvement_provider
            self.improvement.research.provider_factory = self.improvement_provider
        self.capability_imports = CapabilityImports(self)
        self.capability_settings = CapabilitySettings(self)
        self.capability_markets = CapabilityMarkets(self)
        register_market_commands(self.tools, self.capability_markets)
        self.professional_capabilities = ProfessionalCapabilities(self)
        if isinstance(self.executor, CodingExecutor):
            self.executor.capabilities = self.professional_capabilities

    def improvement_provider(self, settings, role):
        actual = "main" if role in {"main", "artifact_a"} else "worker"
        return configured_provider(settings, actual)

    async def run_turn(self, turn, *args, **kwargs):
        if self.improvement is None or not self.improvement.ledger.path.exists():
            return await self.loop.run(turn, *args, **kwargs)

        def scope(db):
            root = origin_turn(db, turn["owner_id"], turn_id=turn["id"])
            return dict(
                db.execute(
                    "SELECT id,created_ms FROM conversations WHERE id=? AND owner_id=?",
                    (root["conversation_id"], turn["owner_id"]),
                ).fetchone()
            )

        conversation = await self.db.call(scope)
        baseline = {key: getattr(self.settings.current, key) for key in BOUNDS}
        binding = await asyncio.to_thread(
            self.improvement.releases.bind,
            turn["owner_id"],
            conversation["id"],
            conversation["created_ms"],
            baseline,
        )
        token = policy_binding.set(binding)
        try:
            return await self.loop.run(turn, *args, **kwargs)
        finally:
            policy_binding.reset(token)

    async def start(self):
        self.mcp.start()
        await self.mcp.refresh()
        await self.professional_capabilities.recover()
        await self.model_settings.refresh_capacity()
        await self.conversations.recover()
        await self.memory_jobs.recover()
        await self.resources.recover()
        await self.dispatch.recover()
        await self.briefs.recover()
        await self.native_sessions.recover()
        if self.settings.proactive_enabled:
            await self.proactive.recover()
        self.supervisor = asyncio.create_task(self.scheduler.run(), name="roami-agent-supervisor")
        if self.executor and getattr(self.executor, "can_reconcile", False):
            self.external_monitor = asyncio.create_task(self._monitor_external())
        self.browser_monitor = asyncio.create_task(self._monitor_browser())
        self.desktop_monitor = asyncio.create_task(self._monitor_desktop())
        self.control_monitor = asyncio.create_task(self._monitor_controls())
        self.reminder_monitor = asyncio.create_task(self._monitor_reminders())
        self.brief_monitor = asyncio.create_task(self._monitor_briefs())
        self.artifact_monitor = asyncio.create_task(self._monitor_artifacts())
        self.native_session_monitor = asyncio.create_task(self._monitor_native_sessions())
        if self.db.managed:
            self.native_reconciliation_monitor = asyncio.create_task(
                self._monitor_native_reconciliation()
            )
        if self.settings.proactive_enabled:
            self.proactive_monitor = asyncio.create_task(self._monitor_proactive())
        self.wakeup.set()
        if self.db.managed and self.improvement is not None:
            from roami_agent.improvement.workflows.worker import EvaluationWorker

            self.improvement.worker = EvaluationWorker(self, self.improvement)
            await self.improvement.worker.start()
            from roami_agent.improvement.workflows.research_worker import ResearchWorker

            self.improvement.research_worker = ResearchWorker(self, self.improvement)
            await self.improvement.research_worker.start()
            from roami_agent.improvement.workflows.pipeline_reports import PipelineReportWorker

            self.improvement.report_worker = PipelineReportWorker(
                self.improvement, settings=lambda: self.settings.current
            )
            await self.improvement.report_worker.start()

    async def _monitor_native_sessions(self):
        while not self.stopping:
            try:
                await self.native_sessions.maintain()
            except (DomainError, OSError, ValueError):
                log.exception("Native session projection failed")
            await asyncio.sleep(5)

    async def _monitor_native_reconciliation(self):
        while not self.stopping:
            try:
                await self.native_reconciliation.tick()
            except (DomainError, OSError, TimeoutError):
                log.exception("Native workspace stop reconciliation failed")
            await asyncio.sleep(2)

    async def _monitor_artifacts(self):
        while not self.stopping:
            await asyncio.sleep(self.artifact_retention.interval_seconds)
            if self.stopping:
                return
            try:
                summary = await self.artifact_retention.collect()
                if summary["errors"]:
                    log.warning("Artifact retention skipped unsafe or unavailable files")
            except (DomainError, OSError):
                log.exception("Artifact retention failed")

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
                if not self.reconfiguring:
                    await self.proactive.tick()
            except Exception:
                log.exception("Proactive evaluation failed")
            await asyncio.sleep(1)

    async def _monitor_briefs(self):
        while not self.stopping:
            try:
                if not self.reconfiguring:
                    await self.briefs.tick()
            except Exception:
                log.exception("Daily brief scheduling failed")
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
        self.mcp.shutting_down = True
        if self.improvement is not None and self.improvement.report_worker:
            await self.improvement.report_worker.close()
        if self.improvement is not None and self.improvement.research_worker:
            await self.improvement.research_worker.close()
        if self.improvement is not None and self.improvement.worker:
            await self.improvement.worker.close()
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
        if self.brief_monitor:
            self.brief_monitor.cancel()
            await asyncio.gather(self.brief_monitor, return_exceptions=True)
        if self.browser_monitor:
            self.browser_monitor.cancel()
            await asyncio.gather(self.browser_monitor, return_exceptions=True)
        if self.desktop_monitor:
            self.desktop_monitor.cancel()
            await asyncio.gather(self.desktop_monitor, return_exceptions=True)
        if self.native_reconciliation_monitor:
            self.native_reconciliation_monitor.cancel()
            await asyncio.gather(self.native_reconciliation_monitor, return_exceptions=True)
        if self.artifact_monitor:
            self.artifact_monitor.cancel()
            await asyncio.gather(self.artifact_monitor, return_exceptions=True)
        if self.control_monitor:
            self.control_monitor.cancel()
            await asyncio.gather(self.control_monitor, return_exceptions=True)
        if self.native_session_monitor:
            self.native_session_monitor.cancel()
            await asyncio.gather(self.native_session_monitor, return_exceptions=True)
        running = [item["handle"] for item in self.active.values()]
        for handle in running:
            handle.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        await self.native_sessions.flush()
        await self.professional_capabilities.close()
        await self.capability_markets.close()
        await self.mcp.close()
        await self.desktop.close()
        await self.files.close()
        await self.artifact_retention.close()
        await self.artifacts.close()
        await self.model_settings.close()


async def serve(args):
    from roami_agent.server.http import create_app

    settings = load_model_settings(Settings.load(args.config), args.data_root)
    validate_servers(settings.mcp_servers)
    database = Database(args.database, args.data_root)
    await database.open()
    if args.initialize:
        await database.close()
        return

    provider = configured_provider(settings, "main")
    worker = configured_provider(settings, "worker")
    runtime = Runtime(
        database,
        provider,
        settings=settings,
        worker_model=worker,
        executor=CodingExecutor(database, settings),
        development_rsi=getattr(args, "development_rsi", False),
    )
    runtime.managed_parent = getattr(args, "parent_fd", None) is not None
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
                uvicorn.Config(
                    create_app(runtime),
                    uds=str(args.socket),
                    log_level="info",
                    timeout_graceful_shutdown=3,
                )
            )
            parent_fd = getattr(args, "parent_fd", None)
            loop = asyncio.get_running_loop()
            if parent_fd is not None:

                def parent_closed():
                    if not os.read(parent_fd, 1):
                        server.should_exit = True
                        loop.remove_reader(parent_fd)

                loop.add_reader(parent_fd, parent_closed)
            try:
                await server.serve(sockets=[bound])
            finally:
                if parent_fd is not None:
                    loop.remove_reader(parent_fd)
                    os.close(parent_fd)
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
    parser.add_argument("--development-rsi", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--parent-fd", type=int)
    args = parser.parse_args()
    if not args.initialize and not args.socket:
        parser.error("--socket is required when serving")
    asyncio.run(serve(args))


if __name__ == "__main__":
    main()
