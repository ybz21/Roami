"""Owner-scoped transactional persistence for diagnostic requests."""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from roami_agent.improvement.domain.contracts import digest, require
from roami_agent.improvement.evaluation.artifact_review import needs_artifact_review
from roami_agent.improvement.evaluation.contracts import load_suite
from roami_agent.improvement.persistence.operation_accounting import assert_operation_costs_settled
from roami_agent.improvement.persistence.run_repository import RunRepository
from roami_agent.protocol.identity import now_ms


def enqueue_diagnostic_request(
    ledger, owner, key, prefs, case_ids, config, reviewer, baseline, shared
):
    with ledger.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        assert_operation_costs_settled(db, owner, shared=shared)
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
        suite = load_suite(Path(source["path"]))
        require(suite["content_hash"] == source["content_hash"], "RSI_SUITE_HASH_MISMATCH")
        require(set(case_ids) <= {c["id"] for c in suite["cases"]}, "RSI_CASE_NOT_FOUND")
        artifact_count = sum(
            needs_artifact_review(c) for c in suite["cases"] if c["id"] in case_ids
        )
        artifact_reservation = reviewer.profile["max_tokens"] * artifact_count if reviewer else 0
        if not shared:
            today = datetime.now(ZoneInfo(prefs["timezone"])).date().isoformat()
            reserve = (
                config["generation_tokens"] + config["codex_tokens"] * 2 + artifact_reservation
            )
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
        RunRepository.create_tx(db, owner, run_id, key, "diagnostic", snapshot)
        db.execute(
            "INSERT INTO rsi_requests VALUES(?,?,?,'manual','queued',?,?,NULL,NULL,NULL,?)",
            (run_id, owner, profile["id"], now_ms(), now_ms(), json.dumps(request)),
        )
    return {"id": run_id}


def existing_request(ledger, owner, key):
    with ledger.connection() as db:
        prior = db.execute(
            "SELECT id FROM rsi_pipeline_runs WHERE owner=? AND request_key=?", (owner, key)
        ).fetchone()
        if prior:
            return {"id": prior[0]}
    return None


def heartbeat_request(ledger, request_id):
    with ledger.connection() as db:
        state = db.execute("SELECT state FROM rsi_requests WHERE id=?", (request_id,)).fetchone()[0]
        db.execute(
            "UPDATE rsi_requests SET updated_ms=? WHERE id=? AND state='running'",
            (now_ms(), request_id),
        )
    return state
