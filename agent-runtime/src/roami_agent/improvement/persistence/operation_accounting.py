"""Retain the full reservation of an ended request without inventing its bill."""

import json
from pathlib import Path

from roami_agent.improvement.domain.contracts import digest, require
from roami_agent.protocol.identity import identity, now_ms


def archive_rejected_admission(ledger, owner, operation, *, pipeline=False):
    table = "rsi_pipeline_costs" if pipeline else "rsi_operation_costs"
    with ledger.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            f"SELECT * FROM {table} WHERE id=? AND owner=?", (operation, owner)
        ).fetchone()
        if row is None or row["state"] != "completed":
            return
        value = json.loads(row["result_json"]).get("value", {})
        require(
            value.get("admission_rejected") is True and value.get("metrics", {}).get("tokens") == 0,
            "RSI_OPERATION_CONFLICT",
        )
        values = dict(row)
        values["id"] = operation + ":admission:" + identity()
        columns = list(values)
        db.execute(
            f"INSERT INTO {table} ("
            + ",".join(columns)
            + ") VALUES("
            + ",".join("?" for _ in columns)
            + ")",
            tuple(values.values()),
        )
        db.execute(f"DELETE FROM {table} WHERE id=? AND owner=?", (operation, owner))


def quarantine_operation(ledger, owner, operation, *, reason, evidence):
    require(
        isinstance(reason, str) and 20 <= len(reason) <= 2000, "RSI_RECONCILIATION_REASON_REQUIRED"
    )
    path = Path(evidence)
    require(
        path.is_file() and not path.is_symlink() and path.stat().st_size <= 1_000_000,
        "RSI_RECONCILIATION_EVIDENCE_REQUIRED",
    )
    receipt = {
        "kind": "quarantined",
        "reason": reason,
        "evidence_hash": digest(path.read_text()),
        "recorded_ms": now_ms(),
    }
    with ledger.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM rsi_operation_costs WHERE owner=? AND id=?", (owner, operation)
        ).fetchone()
        require(row is not None, "RSI_OPERATION_NOT_FOUND")
        require(row["state"] == "unknown" and row["reserved"] > 0, "RSI_OPERATION_CONFLICT")
        result = json.loads(row["result_json"])
        require(result["value"]["metrics"].get("tokens") is None, "RSI_OPERATION_CONFLICT")
        receipt["reservation_retained"] = row["reserved"]
        result["reconciliation"] = receipt
        db.execute(
            "UPDATE rsi_operation_costs SET state='quarantined',result_json=? WHERE owner=? AND id=? AND state='unknown'",
            (json.dumps(result), owner, operation),
        )
    return receipt


def assert_operation_costs_settled(db, owner, *, shared=False):
    require(
        not db.execute(
            "SELECT 1 FROM rsi_operation_costs WHERE owner=? AND (state NOT IN ('completed','quarantined') OR (state='completed' AND (json_type(result_json,'$.value.metrics.tokens') IS NOT 'integer' OR (json_extract(result_json,'$.value.metrics.tokens')>reserved AND COALESCE(json_extract(result_json,'$.value.spending_policy'),'frozen_protocol')!='shared_model_daily' AND ?))))",
            (owner, not shared),
        ).fetchone(),
        "RSI_UNKNOWN_OPERATION_REQUIRES_RECONCILIATION",
    )
