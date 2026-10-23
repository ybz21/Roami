"""Independent, restartable RSI review/repair/verification lane."""

import asyncio
import logging

from roami_agent.improvement.behavior_observer import observe_cycle
from roami_agent.improvement.candidate_checks import verify_candidate
from roami_agent.improvement.release_observation import activate_code, observe_code
from roami_agent.improvement.source_revision import SourceRevisions
from roami_agent.protocol.errors import DomainError

log = logging.getLogger(__name__)


class ResearchWorker:
    def __init__(self, runtime, service, *, handlers=None):
        self.runtime, self.service = runtime, service
        self.workflow = service.research
        self.task = None
        self.revisions = SourceRevisions(service.ledger.path.parent / "source")
        self.handlers = handlers

    async def start(self):
        self.task = asyncio.create_task(self.run(), name="roami-rsi-research")

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def run(self):
        while True:
            try:
                if self.service.ledger.path.exists():
                    await asyncio.to_thread(self.workflow.discover)
                    action = await asyncio.to_thread(self.workflow.claim)
                    if action:
                        await self.execute(action)
                        continue
            except (DomainError, OSError, ValueError):
                log.exception("RSI research iteration failed")
            await asyncio.sleep(5)

    async def execute(self, action):
        async def renew():
            while True:
                await asyncio.sleep(15)
                await asyncio.to_thread(self.workflow.heartbeat, action)

        heartbeat = asyncio.create_task(renew())
        try:
            config = await asyncio.to_thread(self.workflow.settings, action["owner"])
            settings = self.runtime.settings.current
            if self.handlers:
                result = await self.handlers[action["kind"]](action, config)
            elif action["kind"] == "review":
                result = await observe_cycle(self.workflow, action, settings, config)
                result["observation"] = (
                    await asyncio.to_thread(
                        observe_code, self.workflow, action["owner"], action["payload"]["cycle_id"]
                    )
                    or {}
                )
            elif action["kind"] == "repair":
                result = await self.revisions.repair(self.workflow, action, settings, config)
            elif action["kind"] == "verify":
                result = await verify_candidate(self.workflow, action, settings, config)
            elif action["kind"] == "publish":
                from roami_agent.improvement.github_publication import publish_verified

                result = await publish_verified(
                    self.workflow, action, self.revisions, config, settings
                )
            elif action["kind"] == "activate":
                result = await activate_code(self.workflow, action, self.revisions, config)
            else:
                raise DomainError("RSI_UNKNOWN_ACTION")
            transitions = {
                "review": (None, None),
                "repair": ("verify", "verifying"),
                "verify": ("activate", "ready"),
                "publish": ("activate", "ready"),
                "activate": (None, "observing"),
            }
            next_kind, item_state = transitions[action["kind"]]
            if action["kind"] == "verify":
                from roami_agent.improvement.github_publication import publication_profile

                if publication_profile(self.service.ledger.path.parent, action["owner"]):
                    next_kind = "publish"
            await asyncio.to_thread(
                self.workflow.complete, action, result, next_kind=next_kind, item_state=item_state
            )
        except asyncio.CancelledError:
            # The lease expires after shutdown; paid operations remain non-replayable until reconciled.
            raise
        except (DomainError, OSError, ValueError, KeyError, TypeError) as error:
            code = error.code if isinstance(error, DomainError) else "RSI_RESEARCH_INVALID_EVIDENCE"
            if (
                code in {"RSI_PROMOTION_REJECTED", "RSI_CANDIDATE_REGRESSION_FAILED"}
                and action["kind"] == "verify"
            ):
                attempt = action["payload"].get("attempt", 1)
                if attempt < config["max_attempts"]:
                    finding = {**action["payload"]["finding"], "previous_attempt_error": code}
                    # A new subject suffix creates an idempotent action without losing the original item.
                    await asyncio.to_thread(self.retry, action, finding, attempt + 1)
                else:
                    await asyncio.to_thread(
                        self.workflow.block, action, "RSI_REPAIR_ATTEMPTS_EXHAUSTED"
                    )
            else:
                await asyncio.to_thread(self.workflow.block, action, code)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    def retry(self, action, finding, attempt):
        item_id = action["payload"].get("improvement_id", action["subject"])
        with self.workflow.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.workflow._owned_action(db, action)
            db.execute(
                "UPDATE rsi_actions SET state='done',error_code='RSI_CANDIDATE_REJECTED',lease=NULL,expires_ms=NULL WHERE id=?",
                (action["id"],),
            )
            # Keep the improvement subject; action identity includes an attempt in the kind key.
            identifier = self.workflow._enqueue(
                db,
                action["owner"],
                "repair",
                item_id + ":" + str(attempt),
                {"finding": finding, "attempt": attempt, "improvement_id": item_id},
            )
            db.execute(
                "UPDATE rsi_improvements SET state='diagnosing',revision=revision+1 WHERE id=? AND owner=?",
                (item_id, action["owner"]),
            )
            return identifier
