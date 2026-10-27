"""Read-only admission estimates; preview never runs agents or changes configuration."""

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from roami_agent.improvement.artifact_review import ArtifactReviewer, needs_artifact_review
from roami_agent.improvement.contracts import load_suite, require
from roami_agent.protocol.errors import DomainError


def preview(service, owner, settings):
    prefs = service.control.preferences(owner)
    shared = getattr(service.ledger, "shared_daily_limit", False)
    catalog = service.control.catalog(owner)
    selected = next((s for s in catalog["suites"] if s["id"] == prefs["suite_id"]), None)
    blockers, tokens, artifact_count = [], None, 0
    if not selected:
        blockers.append("RSI_SUITE_NOT_FOUND")
    else:
        if not selected.get("daily_coverage", {}).get("complete"):
            blockers.append("RSI_FORMAL_SUITE_INCOMPLETE")
        with service.ledger.connection() as db:
            source = db.execute(
                "SELECT path,content_hash FROM rsi_suites WHERE owner=? AND id=?",
                (owner, prefs["suite_id"]),
            ).fetchone()
        try:
            suite = load_suite(Path(source["path"]))
            require(suite["content_hash"] == source["content_hash"], "RSI_SUITE_HASH_MISMATCH")
            artifact_count = sum(needs_artifact_review(c) for c in suite["cases"])
            tokens = sum(
                c["limits"]["tokens"] for c in suite["cases"] if c["judge"]["kind"] != "mechanism"
            )
            if artifact_count:
                reviewer = ArtifactReviewer.load(settings, service.ledger.path.parent, owner)
                require(reviewer is not None, "RSI_ARTIFACT_REVIEW_REQUIRED")
                tokens += artifact_count * reviewer.profile["max_tokens"]
        except DomainError as exc:
            blockers.append(exc.code)
            tokens = None
        except OSError:
            blockers.append("RSI_SUITE_NOT_FOUND")
            tokens = None
    machines = len(prefs["machine_ids"])
    episodes = (60 if shared else 120) * machines
    if not machines:
        blockers.append("RSI_MACHINE_NOT_FOUND")
    if not shared and prefs["daily_episodes"] < episodes:
        blockers.append("RSI_EPISODE_BUDGET")
    reservation = tokens * 2 * machines if tokens is not None and machines else None
    if not shared and (
        not prefs["daily_tokens"]
        or (reservation is not None and prefs["daily_tokens"] < reservation)
    ):
        blockers.append("RSI_BUDGET_REQUIRED")
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
        "reservation_tokens": None if shared else reservation,
        "spending_policy": "shared_model_daily" if shared else "frozen_protocol",
        "artifact_cases": artifact_count,
        "schedule_enabled": prefs["enabled"],
        "next_run": next_run.isoformat() if prefs["enabled"] else None,
        "research_enabled": research["enabled"],
        "codex_tokens_per_operation": None if shared else research["model_tokens"],
        "blockers": list(dict.fromkeys(blockers)),
        "runtime_preflight_required": True,
    }
