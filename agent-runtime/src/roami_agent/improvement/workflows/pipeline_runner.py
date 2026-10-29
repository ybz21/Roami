"""Bounded diagnostic runs on the same queue as the formal daily evaluator."""

import asyncio
import copy
import json
import re
from dataclasses import replace
from pathlib import Path

from roami_agent.improvement.domain.admission_blocking import MODEL_ADMISSION_BLOCKERS
from roami_agent.improvement.domain.contracts import digest, identifier, require
from roami_agent.improvement.domain.policy import BOUNDS
from roami_agent.improvement.evaluation.contracts import load_suite
from roami_agent.improvement.evaluation.trial_evidence import trial_summary
from roami_agent.improvement.integrations.measurements import EpisodeBudget, MeteredModel
from roami_agent.improvement.integrations.spending_policy import (
    uses_shared_model_limit,
)
from roami_agent.improvement.persistence.diagnostic_requests import (
    enqueue_diagnostic_request,
    existing_request,
)

LIGHT_CASES = (
    "CODE-01",
    "QUANT-01",
    "DOC-05",
    "DEMO-01",
    "NEWS-01",
    "finqa:4f978c08853a6db6",
    "MECH-MR01",
    "MECH-CT01",
    "MECH-TL01",
    "MECH-MB01",
)


def enqueue_diagnostic(service, owner, payload, settings=None):
    require(
        isinstance(payload, dict) and set(payload) <= {"request_key", "case_ids", "baseline_run"},
        "RSI_INVALID_REQUEST",
    )
    key = identifier(payload.get("request_key"))
    case_ids = payload.get("case_ids", list(LIGHT_CASES))
    require(
        isinstance(case_ids, list)
        and 1 <= len(case_ids) <= 60
        and all(isinstance(c, str) and 0 < len(c) <= 160 for c in case_ids)
        and len(set(case_ids)) == len(case_ids),
        "RSI_INVALID_REQUEST",
    )
    records = service.runs
    shared = uses_shared_model_limit(service.ledger)
    prior_result = existing_request(service.ledger, owner, key)
    if prior_result is not None:
        return prior_result
    from roami_agent.improvement.evaluation.artifact_review import (
        ArtifactReviewer,
        needs_artifact_review,
    )

    config = records.settings(owner)
    prefs = service.control.preferences(owner)
    baseline = records.get(owner, payload["baseline_run"]) if payload.get("baseline_run") else None
    if baseline:
        case_ids = baseline["snapshot"]["case_ids"]
        require(
            isinstance(case_ids, list)
            and 1 <= len(case_ids) <= 60
            and all(isinstance(c, str) and c for c in case_ids),
            "RSI_CASES_UNAVAILABLE",
        )
    require(prefs["suite_id"] and prefs["machine_ids"], "RSI_SETUP_REQUIRED")
    review_needed = any(needs_artifact_review({"id": case_id}) for case_id in case_ids)
    reviewer = (
        ArtifactReviewer.load(
            settings, service.ledger.path.parent, owner, shared_daily_limit=shared
        )
        if review_needed and settings is not None
        else None
    )
    profile_path = (
        service.ledger.path.parent / "artifact-review" / digest(owner)[:24] / "profile.json"
    )
    require(
        not review_needed or settings is not None or not profile_path.exists(),
        "RSI_ARTIFACT_SETTINGS_REQUIRED",
    )
    return enqueue_diagnostic_request(
        service.ledger, owner, key, prefs, case_ids, config, reviewer, baseline, shared
    )


async def execute_diagnostic(runtime, service, request, *, executor_image=None):
    from roami_agent.improvement.evaluation.execution.containers import ContainerExecutor
    from roami_agent.protocol.errors import DomainError
    from roami_agent.providers.factory import configured_provider

    payload = json.loads(request["payload_json"])
    spec = payload["diagnostic"]
    owner, run_id, config = request["owner"], spec["run_id"], spec["config"]
    shared = uses_shared_model_limit(service.ledger)
    records = service.runs
    records.set_state(owner, run_id, "running")
    records.node(owner, run_id, "evaluate", "running")
    suite = await asyncio.to_thread(load_suite, Path(payload["suite"]["path"]))
    require(suite["content_hash"] == payload["suite"]["content_hash"], "RSI_SUITE_HASH_MISMATCH")
    require(set(spec["case_ids"]) <= {c["id"] for c in suite["cases"]}, "RSI_CASE_NOT_FOUND")
    await asyncio.to_thread(service.run_lifecycle.freeze_cases, owner, run_id, suite)
    settings = runtime.settings.current
    from roami_agent.improvement.evaluation.artifact_review import (
        ArtifactReviewer,
        needs_artifact_review,
    )

    shared_provider = getattr(service, "provider_factory", None)
    artifact_reviewer = (
        ArtifactReviewer.load(
            settings,
            service.ledger.path.parent,
            owner,
            provider_factory=shared_provider,
            shared_daily_limit=shared,
        )
        if any(needs_artifact_review({"id": cid}) for cid in spec["case_ids"])
        else None
    )
    require(
        (artifact_reviewer.content_hash if artifact_reviewer else None)
        == spec.get("artifact_review_hash"),
        "RSI_ARTIFACT_PROFILE_CHANGED",
    )
    budget = EpisodeBudget(
        {"tokens": config["generation_tokens"], "seconds": 14400, "requests": 300},
        observation_id=run_id,
        shared_daily_limit=shared,
    )
    journal = []

    def provider(settings_, role):
        actual = "main" if role in {"main", "artifact_a"} else "worker"
        return MeteredModel(
            shared_provider(settings_, role)
            if shared_provider
            else configured_provider(settings_, actual),
            budget,
            role,
            output_cap=settings_.route(actual).parameters.get("max_tokens") or 0,
            journal=journal,
        )

    main_route = (
        replace(settings.route("main"), name=config["main_model"])
        if config.get("main_model") and not shared
        else None
    )
    worker_route = (
        replace(settings.route("worker"), name=config["worker_model"])
        if config.get("worker_model") and not shared
        else None
    )
    memory_route = (
        replace(worker_route or settings.route("worker"), name=config["memory_model"])
        if config.get("memory_model") and not shared
        else None
    )
    generation_overrides = {
        role: {"reasoning_effort": config[role + "_reasoning_effort"]}
        for role in ("main", "worker", "memory")
        if config.get(role + "_reasoning_effort") and not shared
    }
    executor = ContainerExecutor(
        settings,
        **({"image": executor_image} if executor_image else {}),
        memory_route=memory_route,
        worker_route=worker_route,
        main_route=main_route,
        artifact_reviewer=artifact_reviewer,
        generation_overrides=generation_overrides,
        provider_factory=provider,
        shared_budget=budget,
        shared_daily_limit=shared,
        output_caps={}
        if shared
        else {
            "main": config.get("main_output_tokens", config["output_tokens"]),
            "worker": config.get("worker_output_tokens", config["output_tokens"]),
            "memory": config["memory_output_tokens"],
        },
    )
    fingerprint = await executor.preflight()
    from roami_agent.improvement.evaluation.comparison_context import comparison_context

    await asyncio.to_thread(
        records.freeze_context, owner, run_id, comparison_context(suite, executor, fingerprint)
    )
    records.artifact(owner, run_id, "evaluate", "environment.json", fingerprint)
    policy = {k: getattr(settings, k) for k in BOUNDS}
    directory = records.directory(owner, run_id)
    outcomes = []
    artifact_tokens = 0
    usage_blocker = None
    real_cases = sum(
        c["judge"]["kind"] != "mechanism" for c in suite["cases"] if c["id"] in spec["case_ids"]
    )
    minimum_start = min(32000, config["generation_tokens"] // max(1, real_cases))
    remaining_real = real_cases
    records.artifact(
        owner,
        run_id,
        "evaluate",
        "budget-plan.json",
        {
            "spending_policy": "shared_model_daily",
            "admission": "go_gateway",
            "technical_timeout_seconds": 14400,
        }
        if shared
        else {
            "minimum_start_tokens": minimum_start,
            "real_cases": real_cases,
            "total": config["generation_tokens"],
        },
    )
    for case_id in spec["case_ids"]:
        original = next(c for c in suite["cases"] if c["id"] == case_id)
        case = copy.deepcopy(original)
        if case["judge"]["kind"] != "mechanism" and not shared:
            remaining_real -= 1
            budget.limits["tokens"] = config["generation_tokens"] - remaining_real * minimum_start
            case["limits"]["tokens"] = min(
                case["limits"]["tokens"], max(1, budget.limits["tokens"] - budget.used)
            )
        target = directory / ("case-" + digest(case_id)[:20])
        target.mkdir(mode=0o700)
        records.artifact(
            owner,
            run_id,
            "evaluate",
            "budget-" + digest(case_id)[:20] + ".json",
            {
                "case_id": case_id,
                "spending_policy": "shared_model_daily" if shared else "frozen_protocol",
                "original_limits": original["limits"],
                "effective_limits": {**case["limits"], "tokens": None, "requests": None}
                if shared
                else case["limits"],
                "run_tokens_used": budget.used,
                "run_token_limit": None if shared else budget.limits["tokens"],
                "reserved_for_later_cases": None if shared else remaining_real * minimum_start,
            },
        )
        blocked_by = None
        if usage_blocker is not None and case["judge"]["kind"] != "mechanism":
            blocked_by = usage_blocker
            result = {
                "grade": {"passed": False, "reason": usage_blocker["code"]},
                "metrics": {
                    "tokens": 0,
                    "token_coverage": "complete",
                    "model_calls": 0,
                    "tool_calls": 0,
                    "elapsed_ms": 0,
                    "model_ms": 0,
                },
            }
        else:
            try:
                result = await executor.run(case, policy, target)
            except (DomainError, OSError, ValueError) as exc:
                result = {
                    "grade": {
                        "passed": False,
                        "reason": getattr(exc, "code", "RSI_ENVIRONMENT_UNAVAILABLE"),
                    },
                    "metrics": {"tokens": None, "token_coverage": "unknown"},
                }
        review_tokens = result.get("metrics", {}).get("artifact_review_tokens", 0)
        artifact_tokens = (
            artifact_tokens + review_tokens
            if artifact_tokens is not None and review_tokens is not None
            else None
        )
        result.pop("shared_admission_managed", None)
        if shared:
            result["shared_admission_managed"] = True
        summary = trial_summary(original, result, target)
        if blocked_by is not None:
            summary["blocked_by"] = blocked_by
        elif usage_blocker is None:
            cause = None
            if (budget.unknown or artifact_tokens is None) and not result.get(
                "shared_admission_managed"
            ):
                cause = result.get("admission_error") or "RSI_USAGE_UNKNOWN"
            elif not summary["passed"]:
                cause = next((c for c in MODEL_ADMISSION_BLOCKERS if c in summary["signals"]), None)
            if cause:
                usage_blocker = {"case_id": case_id, "code": cause}
                summary["signals"] = sorted(set(summary["signals"]) | {cause})
                summary["state"] = "blocked"
        records.case(owner, run_id, summary)
        outcomes.append(summary)
        if case["split"] == "development":
            workspace = target / "workspace"
            for path in workspace.rglob("*"):
                if (
                    not path.is_file()
                    or path.is_symlink()
                    or not path.resolve().is_relative_to(workspace.resolve())
                    or path.suffix not in {".py", ".md", ".json", ".csv", ".html", ".svg"}
                    or "__pycache__" in path.parts
                    or path.stat().st_size > 64000
                ):
                    continue
                relative = str(path.relative_to(workspace))
                old = original.get("files", {}).get(relative)
                if old is not None and path.read_bytes() == old.encode():
                    continue
                name = (
                    digest([case_id, relative])[:20]
                    + "-"
                    + re.sub(r"[^A-Za-z0-9_.-]", "_", path.name)[:99]
                )
                records.artifact(
                    owner,
                    run_id,
                    "evaluate",
                    name,
                    path.read_text(errors="replace"),
                )
    records.artifact(owner, run_id, "evaluate", "results.json", outcomes)
    records.artifact(owner, run_id, "evaluate", "provider-usage.json", budget.metrics())
    records.observations(owner, run_id)
    records.node(
        owner,
        run_id,
        "evaluate",
        "blocked" if usage_blocker else "succeeded",
        usage_blocker["code"] if usage_blocker else None,
    )
    records.set_state(
        owner,
        run_id,
        "running",
        {
            "cases": len(outcomes),
            "passed": sum(
                c["state"] == "passed" and c["metrics"].get("tokens") is not None for c in outcomes
            ),
            "pending": sum(c["pending"] for c in outcomes),
            "blocked": sum(c["state"] == "blocked" for c in outcomes),
            "not_run": sum("blocked_by" in c for c in outcomes),
            "usage_blocker": usage_blocker,
            "generation_tokens": budget.metrics()["tokens"],
            "known_generation_tokens": budget.used,
            "artifact_review_tokens": artifact_tokens,
            "provider_requests": budget.metrics()["request_attempts"],
            "known_provider_requests": sum(r["requestAttempts"] or 0 for r in budget.requests),
        },
    )
    from roami_agent.improvement.workflows.pipeline_reports import store_evaluation_summary

    store_evaluation_summary(records, owner, run_id)
    records.set_state(owner, run_id, "report_queued")
