"""Durable run-scoped operation admission and receipts."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from roami_agent.improvement.domain.contracts import require
from roami_agent.improvement.integrations.spending_policy import (
    model_proxy_for,
    uses_shared_model_limit,
)
from roami_agent.improvement.persistence.operation_accounting import assert_operation_costs_settled


class RunCosts:
    def __init__(self, records, owner, run_id):
        self.records, self.ledger, self.owner, self.run_id = records, records.ledger, owner, run_id
        self.model_proxy = model_proxy_for(records)

    def day(self, owner):
        if self.model_proxy is not None:
            return self.model_proxy.billing.period()[0]
        return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()

    def operation_result(self, owner, key):
        require(owner == self.owner, "RSI_RUN_NOT_FOUND")
        with self.ledger.connection() as db:
            row = db.execute(
                "SELECT run_id,state,result_json FROM rsi_pipeline_costs WHERE owner=? AND id=?",
                (owner, key),
            ).fetchone()
        if row is None:
            return None
        require(row["run_id"] == self.run_id, "RSI_RUN_NOT_FOUND")
        require(row["state"] == "completed", "RSI_UNKNOWN_OPERATION_REQUIRES_RECONCILIATION")
        return json.loads(row["result_json"])

    def reserve_operation(self, owner, day, key, tokens):
        require(owner == self.owner, "RSI_RUN_NOT_FOUND")
        value = self.records.get(owner, self.run_id)
        snapshot = value["snapshot"]
        shared = uses_shared_model_limit(self.ledger)
        cap = snapshot["pipeline"]["codex_tokens"] * 2
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM rsi_pipeline_costs WHERE id=? AND owner=?", (key, owner)
            ).fetchone()
            if row:
                require(row["run_id"] == self.run_id, "RSI_RUN_NOT_FOUND")
                require(
                    row["state"] == "completed", "RSI_UNKNOWN_OPERATION_REQUIRES_RECONCILIATION"
                )
                return json.loads(row["result_json"])
            summary = value["summary"] or {}
            require(
                all(
                    summary.get(key, 0) is not None
                    for key in ("generation_tokens", "artifact_review_tokens")
                ),
                "RSI_USAGE_UNKNOWN",
            )
            assert_operation_costs_settled(db, owner, shared=uses_shared_model_limit(self.ledger))
            require(not snapshot.get("imported"), "RSI_DAILY_BUDGET")
            rows = db.execute(
                "SELECT * FROM rsi_pipeline_costs WHERE owner=? AND run_id=?", (owner, self.run_id)
            ).fetchall()
            require(
                all(
                    r["state"] == "completed"
                    and (
                        shared
                        or json.loads(r["result_json"])["value"]["metrics"]["tokens"]
                        <= r["reserved"]
                    )
                    for r in rows
                ),
                "RSI_UNKNOWN_OPERATION_REQUIRES_RECONCILIATION",
            )
            require(shared or sum(r["reserved"] for r in rows) + tokens <= cap, "RSI_TOKEN_BUDGET")
            db.execute(
                "INSERT INTO rsi_pipeline_costs VALUES(?,?,?,?,'running',NULL)",
                (key, owner, self.run_id, tokens),
            )
        return None

    def settle_operation(self, owner, key, result):
        with self.ledger.connection() as db:
            require(
                db.execute(
                    "UPDATE rsi_pipeline_costs SET state='completed',result_json=? WHERE id=? AND owner=? AND run_id=? AND state='running'",
                    (json.dumps(result), key, owner, self.run_id),
                ).rowcount
                == 1,
                "RSI_OPERATION_CONFLICT",
            )
