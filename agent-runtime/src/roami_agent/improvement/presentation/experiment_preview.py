"""Read-only admission estimates; preview never runs agents or changes configuration."""

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from roami_agent.improvement.domain.contracts import require
from roami_agent.improvement.evaluation.artifact_review import (
    ArtifactReviewer,
    needs_artifact_review,
)
from roami_agent.improvement.evaluation.contracts import load_suite
from roami_agent.improvement.integrations.spending_policy import uses_shared_model_limit
from roami_agent.improvement.persistence.evidence_queries import suite_source
from roami_agent.protocol.errors import DomainError


def preview(service, owner, settings):
    prefs = service.control.preferences(owner)
    shared = uses_shared_model_limit(service.ledger)
    catalog = service.control.catalog(owner)
    selected = next((s for s in catalog["suites"] if s["id"] == prefs["suite_id"]), None)
    blockers, artifact_count = [], 0
    if not selected:
        blockers.append("RSI_SUITE_NOT_FOUND")
    else:
        if not selected.get("daily_coverage", {}).get("complete"):
            blockers.append("RSI_FORMAL_SUITE_INCOMPLETE")
        source = suite_source(service.ledger, owner, prefs["suite_id"])
        try:
            suite = load_suite(Path(source["path"]))
            require(suite["content_hash"] == source["content_hash"], "RSI_SUITE_HASH_MISMATCH")
            artifact_count = sum(needs_artifact_review(c) for c in suite["cases"])
            if artifact_count:
                reviewer = ArtifactReviewer.load(
                    settings, service.ledger.path.parent, owner, shared_daily_limit=shared
                )
                require(reviewer is not None, "RSI_ARTIFACT_REVIEW_REQUIRED")
        except DomainError as exc:
            blockers.append(exc.code)
        except OSError:
            blockers.append("RSI_SUITE_NOT_FOUND")
    machines = len(prefs["machine_ids"])
    episodes = 60 * machines
    if not machines:
        blockers.append("RSI_MACHINE_NOT_FOUND")
    if not settings.endpoint or not settings.model:
        blockers.append("MODEL_NOT_CONFIGURED")
    now = datetime.now(ZoneInfo(prefs["timezone"]))
    next_run = now.replace(hour=prefs["hour"], minute=0, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    research = service.research.settings(owner)
    return {
        "cases": 60,
        "machines": machines,
        "episodes": episodes,
        "reservation_tokens": None,
        "spending_policy": "shared_model_daily",
        "artifact_cases": artifact_count,
        "schedule_enabled": prefs["enabled"],
        "next_run": next_run.isoformat() if prefs["enabled"] else None,
        "research_enabled": research["enabled"],
        "codex_tokens_per_operation": None,
        "blockers": list(dict.fromkeys(blockers)),
        "runtime_preflight_required": True,
    }
