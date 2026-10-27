"""Retain the full reservation of an ended request without inventing its bill."""

import json
from pathlib import Path

from roami_agent.improvement.contracts import digest, require
from roami_agent.protocol.identity import now_ms


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


def assert_operation_costs_settled(db, owner):
    from roami_agent.providers.model_proxy import model_proxy_context

    ceiling = (
        ""
        if model_proxy_context.get() is not None
        else " OR json_extract(result_json,'$.value.metrics.tokens')>reserved"
    )
    require(
        not db.execute(
            "SELECT 1 FROM rsi_operation_costs WHERE owner=? AND (state NOT IN ('completed','quarantined') OR (state='completed' AND (json_type(result_json,'$.value.metrics.tokens') IS NOT 'integer'"
            + ceiling
            + ")))",
            (owner,),
        ).fetchone(),
        "RSI_UNKNOWN_OPERATION_REQUIRES_RECONCILIATION",
    )
