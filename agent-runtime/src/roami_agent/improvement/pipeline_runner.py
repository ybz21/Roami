"""Bounded diagnostic runs on the same queue as the formal daily evaluator."""

import asyncio
import copy
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from roami_agent.improvement.contracts import digest, identifier, load_suite, require
from roami_agent.improvement.measurements import EpisodeBudget, MeteredModel
from roami_agent.improvement.operation_accounting import assert_operation_costs_settled
from roami_agent.improvement.policy import BOUNDS
from roami_agent.improvement.run_records import RunRecords, trial_summary
from roami_agent.protocol.identity import now_ms

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
    shared = getattr(service.ledger, "shared_daily_limit", False)
    with service.ledger.connection() as db:
        prior = db.execute(
            "SELECT id FROM rsi_pipeline_runs WHERE owner=? AND request_key=?", (owner, key)
        ).fetchone()
        if prior:
            return {"id": prior[0]}
    from roami_agent.improvement.artifact_review import ArtifactReviewer, needs_artifact_review

    reviewer = (
        ArtifactReviewer.load(settings, service.ledger.path.parent, owner)
        if settings is not None
        else None
    )
    profile_path = (
        service.ledger.path.parent / "artifact-review" / digest(owner)[:24] / "profile.json"
    )
    require(settings is not None or not profile_path.exists(), "RSI_ARTIFACT_SETTINGS_REQUIRED")
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
    with service.ledger.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        assert_operation_costs_settled(db, owner)
        machine = db.execute(
            "SELECT profile_json FROM rsi_machines WHERE owner=? AND id=?",
            (owner, prefs["machine_ids"][0]),
        ).fetchone()
        source = db.execute(
            "SELECT path,content_hash FROM rsi_suites WHERE owner=? AND id=?",
            (owner, prefs["suite_id"]),
        ).fetchone()
        require(machine and source, "RSI_SETUP_REQUIRED")
        profile = json.loads(machine[0])
        require(profile["mode"] == "container", "RSI_CODE_CONTAINER_REQUIRED")
        run_id = digest([owner, "diagnostic", key])
        prior = db.execute(
            "SELECT id FROM rsi_pipeline_runs WHERE owner=? AND request_key=?", (owner, key)
        ).fetchone()
        if prior:
            return {"id": prior[0]}
        today = datetime.now(ZoneInfo(prefs["timezone"])).date().isoformat()
        suite = load_suite(Path(source["path"]))
        require(suite["content_hash"] == source["content_hash"], "RSI_SUITE_HASH_MISMATCH")
        require(set(case_ids) <= {c["id"] for c in suite["cases"]}, "RSI_CASE_NOT_FOUND")
        artifact_count = sum(
            needs_artifact_review(c) for c in suite["cases"] if c["id"] in case_ids
        )
        artifact_reservation = reviewer.profile["max_tokens"] * artifact_count if reviewer else 0
        reserve = config["generation_tokens"] + config["codex_tokens"] * 2 + artifact_reservation
        db.execute(
            "INSERT OR IGNORE INTO rsi_budgets VALUES(?,?,?,?,0,0)",
            (owner, today, config["daily_tokens"], prefs["daily_episodes"] or 10000),
        )
        budget = db.execute(
            "SELECT * FROM rsi_budgets WHERE owner=? AND day=?", (owner, today)
        ).fetchone()
        require(
            shared or budget["tokens_reserved"] + reserve <= budget["tokens_limit"],
            "RSI_DAILY_BUDGET",
        )
        require(
            shared or budget["episodes_reserved"] + len(case_ids) <= budget["episodes_limit"],
            "RSI_DAILY_EPISODE_BUDGET",
        )
        db.execute(
            "UPDATE rsi_budgets SET tokens_reserved=tokens_reserved+?,episodes_reserved=episodes_reserved+? WHERE owner=? AND day=?",
            (reserve, len(case_ids), owner, today),
        )
        request = {
            "period_key": key,
            "preferences": prefs,
            "machine": profile,
            "suite": dict(source),
            "diagnostic": {
                "case_ids": case_ids,
                "config": config,
                "run_id": run_id,
                "artifact_review_hash": reviewer.content_hash if reviewer else None,
            },
        }
        snapshot = {
            "spending_policy": "shared_model_daily" if shared else "frozen_protocol",
            "case_ids": case_ids,
            "suite_hash": source["content_hash"],
            "machine_id": profile["id"],
            "pipeline": config,
            "baseline_run": baseline["id"] if baseline else None,
            "formal_daily": False,
            "artifact_review": {
                "hash": reviewer.content_hash if reviewer else None,
                "reservation_tokens": artifact_reservation,
            },
        }
        RunRecords.create_tx(db, owner, run_id, key, "diagnostic", snapshot)
        db.execute(
            "INSERT INTO rsi_requests VALUES(?,?,?,'manual','queued',?,?,NULL,NULL,NULL,?)",
            (run_id, owner, profile["id"], now_ms(), now_ms(), json.dumps(request)),
        )
    return {"id": run_id}


async def execute_diagnostic(runtime, service, request, *, executor_image=None):
    from roami_agent.app import configured_provider
    from roami_agent.improvement.containers import ContainerExecutor
    from roami_agent.protocol.errors import DomainError

    payload = json.loads(request["payload_json"])
    spec = payload["diagnostic"]
    owner, run_id, config = request["owner"], spec["run_id"], spec["config"]
    shared = getattr(service.ledger, "shared_daily_limit", False)
    records = service.runs
    records.set_state(owner, run_id, "running")
    records.node(owner, run_id, "evaluate", "running")
    suite = await asyncio.to_thread(load_suite, Path(payload["suite"]["path"]))
    require(suite["content_hash"] == payload["suite"]["content_hash"], "RSI_SUITE_HASH_MISMATCH")
    require(set(spec["case_ids"]) <= {c["id"] for c in suite["cases"]}, "RSI_CASE_NOT_FOUND")
    await asyncio.to_thread(records.freeze_cases, owner, run_id, suite)
    settings = runtime.settings.current
    from roami_agent.improvement.artifact_review import ArtifactReviewer

    shared_provider = getattr(service, "provider_factory", None)
    artifact_reviewer = ArtifactReviewer.load(
        settings, service.ledger.path.parent, owner, provider_factory=shared_provider
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
        actual = "main" if role == "main" else "worker"
        return MeteredModel(
            shared_provider(settings_, role)
            if shared_provider
            else configured_provider(settings_, actual),
            budget,
            role,
            output_cap=settings_.route(actual).parameters["max_tokens"],
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
    from roami_agent.improvement.comparison_context import comparison_context

    await asyncio.to_thread(
        records.freeze_context, owner, run_id, comparison_context(suite, executor, fingerprint)
    )
    records.artifact(owner, run_id, "evaluate", "environment.json", fingerprint)
    policy = {k: getattr(settings, k) for k in BOUNDS}
    directory = records.directory(owner, run_id)
    outcomes = []
    artifact_tokens = 0
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
            "admission": "model_proxy",
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
                "original_limits": original["limits"],
                "effective_limits": case["limits"],
                "run_tokens_used": budget.used,
                "run_token_limit": budget.limits["tokens"],
                "reserved_for_later_cases": remaining_real * minimum_start,
            },
        )
        if (budget.unknown or artifact_tokens is None) and case["judge"]["kind"] != "mechanism":
            result = {
                "grade": {"passed": False, "reason": "RSI_USAGE_UNKNOWN"},
                "metrics": {"tokens": None, "token_coverage": "unknown"},
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
        summary = trial_summary(original, result, target)
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
                records.artifact(
                    owner,
                    run_id,
                    "evaluate",
                    digest(case_id)[:8] + "-" + path.name,
                    path.read_text(errors="replace"),
                )
    records.artifact(owner, run_id, "evaluate", "results.json", outcomes)
    records.artifact(owner, run_id, "evaluate", "provider-usage.json", budget.metrics())
    records.observations(owner, run_id)
    records.node(
        owner,
        run_id,
        "evaluate",
        "blocked" if budget.unknown or artifact_tokens is None else "succeeded",
        "RSI_USAGE_UNKNOWN" if budget.unknown or artifact_tokens is None else None,
    )
    records.set_state(
        owner,
        run_id,
        "report_queued",
        {
            "cases": len(outcomes),
            "passed": sum(c["passed"] for c in outcomes),
            "pending": sum(c["pending"] for c in outcomes),
            "generation_tokens": budget.metrics()["tokens"],
            "known_generation_tokens": budget.used,
            "artifact_review_tokens": artifact_tokens,
            "provider_requests": len(budget.requests),
        },
    )
