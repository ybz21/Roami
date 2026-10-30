"""Durable run-scoped operation admission and receipts."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from roami_agent.improvement.domain.contracts import require


class RunCosts:
    def __init__(self, records, owner, run_id):
        self.records, self.ledger, self.owner, self.run_id = records, records.ledger, owner, run_id

    def day(self, owner):
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
            require(not value["snapshot"].get("imported"), "RSI_IMPORTED_RUN_READ_ONLY")
            db.execute(
                "INSERT INTO rsi_pipeline_costs VALUES(?,?,?,?,'running',NULL)",
                (key, owner, self.run_id, 0),
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
