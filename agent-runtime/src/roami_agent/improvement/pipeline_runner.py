"""Bounded diagnostic runs on the same queue as the formal daily evaluator."""

import asyncio
import copy
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from roami_agent.improvement.contracts import digest, identifier, load_suite, require
from roami_agent.improvement.measurements import EpisodeBudget, MeteredModel
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


def enqueue_diagnostic(service, owner, payload):
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
        reserve = config["generation_tokens"] + config["codex_tokens"] * 2
        db.execute(
            "INSERT OR IGNORE INTO rsi_budgets VALUES(?,?,?,?,0,0)",
            (owner, today, config["daily_tokens"], 10000),
        )
        budget = db.execute(
            "SELECT * FROM rsi_budgets WHERE owner=? AND day=?", (owner, today)
        ).fetchone()
        require(budget["tokens_reserved"] + reserve <= budget["tokens_limit"], "RSI_DAILY_BUDGET")
        db.execute(
            "UPDATE rsi_budgets SET tokens_reserved=tokens_reserved+?,episodes_reserved=episodes_reserved+? WHERE owner=? AND day=?",
            (reserve, len(case_ids), owner, today),
        )
        request = {
            "period_key": key,
            "preferences": prefs,
            "machine": profile,
            "suite": dict(source),
            "diagnostic": {"case_ids": case_ids, "config": config, "run_id": run_id},
        }
        snapshot = {
            "case_ids": case_ids,
            "suite_hash": source["content_hash"],
            "machine_id": profile["id"],
            "pipeline": config,
            "baseline_run": baseline["id"] if baseline else None,
            "formal_daily": False,
        }
        RunRecords.create_tx(db, owner, run_id, key, "diagnostic", snapshot)
        db.execute(
            "INSERT INTO rsi_requests VALUES(?,?,?,'manual','queued',?,?,NULL,NULL,NULL,?)",
            (run_id, owner, profile["id"], now_ms(), now_ms(), json.dumps(request)),
        )
    return {"id": run_id}


async def execute_diagnostic(runtime, service, request):
    from roami_agent.app import configured_provider
    from roami_agent.improvement.containers import ContainerExecutor
    from roami_agent.protocol.errors import DomainError

    payload = json.loads(request["payload_json"])
    spec = payload["diagnostic"]
    owner, run_id, config = request["owner"], spec["run_id"], spec["config"]
    records = service.runs
    records.set_state(owner, run_id, "running")
    records.node(owner, run_id, "evaluate", "running")
    suite = await asyncio.to_thread(load_suite, Path(payload["suite"]["path"]))
    require(suite["content_hash"] == payload["suite"]["content_hash"], "RSI_SUITE_HASH_MISMATCH")
    require(set(spec["case_ids"]) <= {c["id"] for c in suite["cases"]}, "RSI_CASE_NOT_FOUND")
    settings = runtime.settings.current
    budget = EpisodeBudget(
        {"tokens": config["generation_tokens"], "seconds": 14400, "requests": 300}
    )
    journal = []

    def provider(settings_, role):
        actual = "main" if role == "main" else "worker"
        return MeteredModel(
            configured_provider(settings_, actual),
            budget,
            role,
            output_cap=config["memory_output_tokens"]
            if role == "memory"
            else config["output_tokens"],
            journal=journal,
        )

    executor = ContainerExecutor(
        settings,
        provider_factory=provider,
        output_caps={
            "main": config["output_tokens"],
            "worker": config["output_tokens"],
            "memory": config["memory_output_tokens"],
        },
    )
    fingerprint = await executor.preflight()
    records.artifact(owner, run_id, "evaluate", "environment.json", fingerprint)
    policy = {k: getattr(settings, k) for k in BOUNDS}
    directory = records.directory(owner, run_id)
    outcomes = []
    for case_id in spec["case_ids"]:
        original = next(c for c in suite["cases"] if c["id"] == case_id)
        case = copy.deepcopy(original)
        target = directory / ("case-" + digest(case_id)[:20])
        target.mkdir(mode=0o700)
        if budget.unknown and case["judge"]["kind"] != "mechanism":
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
        "blocked" if budget.unknown else "succeeded",
        "RSI_USAGE_UNKNOWN" if budget.unknown else None,
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
            "provider_requests": len(budget.requests),
        },
    )
