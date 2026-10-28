"""Independent evaluation slot; never enters Main's model or task queue."""

import asyncio
import json
import logging
import platform
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from roami_agent.improvement.domain.contracts import digest, require
from roami_agent.improvement.domain.policy import BOUNDS, next_candidate
from roami_agent.improvement.evaluation.contracts import load_suite
from roami_agent.improvement.integrations.source_identity import implementation_hash
from roami_agent.improvement.integrations.spending_policy import uses_shared_model_limit
from roami_agent.improvement.persistence.diagnostic_requests import heartbeat_request
from roami_agent.protocol.errors import DomainError

log = logging.getLogger(__name__)


class EvaluationWorker:
    def __init__(self, runtime, service):
        self.runtime, self.service = runtime, service
        self.task = None
        self.active = None
        self.request = None

    async def start(self):
        if self.service.ledger.path.exists():
            await asyncio.to_thread(self.service.control.recover)
        self.task = asyncio.create_task(self.monitor(), name="roami-rsi-worker")

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.active:
            self.active.cancel()
            await asyncio.gather(self.active, return_exceptions=True)

    async def monitor(self):
        while True:
            self.service.wakeup.clear()
            if self.service.ledger.path.exists():
                try:
                    if self.active and not self.active.done():
                        state = heartbeat_request(self.service.ledger, self.request["id"])
                        if state == "cancelling":
                            self.active.cancel()
                    else:
                        if self.active:
                            await asyncio.gather(self.active, return_exceptions=True)
                        await asyncio.to_thread(self.service.control.schedule)
                        self.request = await asyncio.to_thread(self.service.control.claim)
                        self.active = (
                            asyncio.create_task(self.execute(self.request))
                            if self.request
                            else None
                        )
                except (DomainError, OSError):
                    log.exception("RSI scheduling failed")
            try:
                await asyncio.wait_for(self.service.wakeup.wait(), timeout=1 if self.active else 30)
            except TimeoutError:
                pass

    async def execute(self, request):
        from roami_agent.improvement.evaluation.execution.executors import (
            ExternalExecutor,
            NativeFilesExecutor,
        )
        from roami_agent.improvement.workflows.cycle import run_cycle

        if hasattr(self.service, "runs"):
            await asyncio.to_thread(self.service.run_lifecycle.begin_request, request)
        try:
            if "diagnostic" in json.loads(request["payload_json"]):
                from roami_agent.improvement.workflows.pipeline_runner import execute_diagnostic

                await execute_diagnostic(self.runtime, self.service, request)
                await asyncio.to_thread(self.service.control.finish, request, "completed")
                return
            prefs, machine, source = await asyncio.to_thread(self.service.control.profiles, request)
            suite = load_suite(Path(source["path"]))
            require(suite["content_hash"] == source["content_hash"], "RSI_SUITE_HASH_MISMATCH")
            if hasattr(self.service, "runs"):
                await asyncio.to_thread(
                    self.service.run_lifecycle.freeze_cases, request["owner"], request["id"], suite
                )
            if request["kind"] == "daily":
                from roami_agent.improvement.evaluation.daily_suite import daily_coverage

                require(
                    daily_coverage(suite)["complete"],
                    "RSI_FORMAL_SUITE_INCOMPLETE",
                )
            settings = self.runtime.settings.current
            provider_factory = getattr(self.service, "provider_factory", None)
            shared = uses_shared_model_limit(self.service.ledger)
            require(
                not shared or machine["mode"] in {"container", "native_files"},
                "RSI_SHARED_MODEL_GATEWAY_REQUIRED",
            )
            if machine["mode"] in {"native_files", "container"}:
                require(settings.endpoint and settings.model, "MODEL_NOT_CONFIGURED")
                if machine["mode"] == "container":
                    from roami_agent.improvement.evaluation.artifact_review import (
                        ArtifactReviewer,
                        needs_artifact_review,
                    )
                    from roami_agent.improvement.evaluation.execution.containers import (
                        ContainerExecutor,
                    )

                    reviewer = ArtifactReviewer.load(
                        settings,
                        self.service.ledger.path.parent,
                        request["owner"],
                        provider_factory=provider_factory,
                        shared_daily_limit=shared,
                    )
                    require(
                        reviewer is not None
                        or not any(needs_artifact_review(c) for c in suite["cases"]),
                        "RSI_ARTIFACT_REVIEW_REQUIRED",
                    )
                    executor = ContainerExecutor(
                        settings,
                        artifact_reviewer=reviewer,
                        provider_factory=provider_factory,
                        shared_daily_limit=shared,
                    )
                    fingerprint = await executor.preflight()
                else:
                    executor = NativeFilesExecutor(
                        settings,
                        settle_maintenance=True,
                        provider_factory=provider_factory,
                        shared_daily_limit=shared,
                    )
                    fingerprint = {}
                machine = {
                    **machine,
                    "environment_hash": digest([platform.uname()._asdict(), implementation_hash()]),
                    **fingerprint,
                    "cache_mode": machine.get("cache_mode", "uncontrolled"),
                }
            else:
                executor = ExternalExecutor(machine["argv"], model_hash=machine["model_hash"])
            baseline = {k: getattr(settings, k) for k in BOUNDS}
            candidate = {**baseline, **prefs["candidate_policy"]}
            if prefs["auto_candidates"]:
                history = [
                    c["report"]
                    for c in self.service.ledger.list(request["owner"], 100)
                    if c["state"] == "completed"
                    and c["report"].get("suite_hash") == suite["content_hash"]
                    and c["report"].get("model_hash") == executor.model_hash
                    and c["report"].get("implementation_hash") == implementation_hash()
                ]
                # Cycle proposals contain development trials only; protected tasks still run.
                candidate = (
                    (next_candidate(baseline, history) or baseline)
                    if any(c["split"] == "development" for c in suite["cases"])
                    else baseline
                )
            source_builds = None
            from roami_agent.improvement.workflows.release_observation import active_code

            release = await asyncio.to_thread(active_code, self.service.research, request["owner"])
            if release:
                from roami_agent.improvement.workflows.candidate_checks import CodePairExecutor

                require(machine["mode"] == "container", "RSI_CODE_CONTAINER_REQUIRED")
                executor = CodePairExecutor(
                    settings,
                    release,
                    artifact_reviewer=reviewer,
                    provider_factory=provider_factory,
                    shared_daily_limit=shared,
                )
                fingerprint = await executor.preflight()
                machine = {**machine, **fingerprint}
                source_builds = executor.builds
                candidate = baseline
            if hasattr(self.service, "runs"):
                from roami_agent.improvement.evaluation.comparison_context import comparison_context

                await asyncio.to_thread(
                    self.service.runs.freeze_context,
                    request["owner"],
                    request["id"],
                    comparison_context(
                        suite,
                        executor,
                        machine,
                        source_hash=source_builds["candidate"] if source_builds else None,
                    ),
                )
            result = await run_cycle(
                ledger=self.service.ledger,
                owner=request["owner"],
                day=datetime.now(ZoneInfo(prefs["timezone"])).date().isoformat(),
                suite=suite,
                machine=machine,
                executor=executor,
                baseline=baseline,
                candidate=candidate,
                output_root=self.service.ledger.path.parent / "runs",
                daily_tokens=prefs["daily_tokens"],
                daily_episodes=prefs["daily_episodes"],
                request_key=request["id"] if request["kind"] == "manual" else "daily",
                schedule_period=prefs["period_key"],
                period_machines=prefs["machine_ids"],
                source_builds=source_builds,
                paired=baseline != candidate or source_builds is not None,
            )
            await asyncio.to_thread(
                self.service.control.finish,
                request,
                "completed" if result.get("full_suite_complete") else "blocked",
                cycle_id=result["cycle_id"],
                error_code=None if result.get("full_suite_complete") else "RSI_REVIEW_INCOMPLETE",
            )
        except asyncio.CancelledError:
            await asyncio.to_thread(
                self.service.control.finish, request, "interrupted", error_code="RSI_CANCELLED"
            )
            raise
        except (DomainError, OSError, ValueError) as error:
            await asyncio.to_thread(
                self.service.control.finish,
                request,
                "blocked",
                error_code=error.code
                if isinstance(error, DomainError)
                else "RSI_ENVIRONMENT_UNAVAILABLE",
            )
        finally:
            if hasattr(self.service, "runs"):
                try:
                    await asyncio.to_thread(self.service.run_lifecycle.capture_request, request)
                except (DomainError, OSError, ValueError, KeyError):
                    log.exception("RSI run capture failed")
            self.service.wakeup.set()
