"""Independent evaluation slot; never enters Main's model or task queue."""

import asyncio
import logging
import platform
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from roami_agent.improvement.contracts import (
    digest,
    implementation_hash,
    load_json,
    require,
    validate_suite,
)
from roami_agent.improvement.policy import BOUNDS, next_candidate
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms

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
                        with self.service.ledger.connection() as db:
                            state = db.execute(
                                "SELECT state FROM rsi_requests WHERE id=?", (self.request["id"],)
                            ).fetchone()[0]
                            db.execute(
                                "UPDATE rsi_requests SET updated_ms=? WHERE id=? AND state='running'",
                                (now_ms(), self.request["id"]),
                            )
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
        from roami_agent.improvement.cycle import run_cycle
        from roami_agent.improvement.executors import ExternalExecutor, NativeFilesExecutor

        try:
            prefs, machine, source = await asyncio.to_thread(self.service.control.profiles, request)
            suite = validate_suite(load_json(Path(source["path"]), maximum=100_000_000))
            require(suite["content_hash"] == source["content_hash"], "RSI_SUITE_HASH_MISMATCH")
            if request["kind"] == "daily":
                require(
                    len(suite["cases"]) == 60
                    and not any(c["layer"] == "smoke" for c in suite["cases"]),
                    "RSI_FORMAL_SUITE_INCOMPLETE",
                )
            settings = self.runtime.settings.current
            if machine["mode"] in {"native_files", "container"}:
                require(settings.endpoint and settings.model, "MODEL_NOT_CONFIGURED")
                if machine["mode"] == "container":
                    from roami_agent.improvement.containers import ContainerExecutor

                    executor = ContainerExecutor(settings)
                    fingerprint = await executor.preflight()
                else:
                    executor = NativeFilesExecutor(settings, settle_maintenance=True)
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
                require(
                    all(c["split"] == "development" for c in suite["cases"]),
                    "RSI_SEARCH_DEVELOPMENT_ONLY",
                )
                history = [
                    c["report"]
                    for c in self.service.ledger.list(request["owner"], 100)
                    if c["state"] == "completed"
                    and c["report"].get("suite_hash") == suite["content_hash"]
                    and c["report"].get("model_hash") == executor.model_hash
                    and c["report"].get("implementation_hash") == implementation_hash()
                ]
                candidate = next_candidate(baseline, history) or baseline
            source_builds = None
            from roami_agent.improvement.release_observation import active_code

            release = await asyncio.to_thread(active_code, self.service.research, request["owner"])
            if release:
                from roami_agent.improvement.candidate_checks import CodePairExecutor

                require(machine["mode"] == "container", "RSI_CODE_CONTAINER_REQUIRED")
                executor = CodePairExecutor(settings, release)
                fingerprint = await executor.preflight()
                machine = {**machine, **fingerprint}
                source_builds = executor.builds
                candidate = baseline
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
                source_builds=source_builds,
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
            self.service.wakeup.set()
