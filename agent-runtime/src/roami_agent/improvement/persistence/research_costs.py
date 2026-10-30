"""ResearchCosts persistence within the research aggregate."""

import json

from roami_agent.improvement.domain.contracts import require


class ResearchCosts:
    def __init__(self, owner):
        self.owner, self.ledger = owner, owner.ledger

    def operation_result(self, owner, key):
        with self.ledger.connection() as db:
            row = db.execute(
                "SELECT state,result_json FROM rsi_operation_costs WHERE owner=? AND id=?",
                (owner, key),
            ).fetchone()
        if row is None:
            return None
        require(row["state"] == "completed", "RSI_UNKNOWN_OPERATION_REQUIRES_RECONCILIATION")
        return json.loads(row["result_json"])

    def reserve_operation(self, owner, day, key, tokens):
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT * FROM rsi_operation_costs WHERE id=? AND owner=?", (key, owner)
            ).fetchone()
            if prior:
                require(
                    prior["state"] == "completed", "RSI_UNKNOWN_OPERATION_REQUIRES_RECONCILIATION"
                )
                return json.loads(prior["result_json"])
            db.execute(
                "INSERT INTO rsi_operation_costs VALUES(?,?,?,?,'running',NULL)",
                (key, owner, day, 0),
            )
        return None

    def settle_operation(self, owner, key, result):
        tokens = result.get("value", {}).get("metrics", {}).get("tokens")
        require(tokens is None or type(tokens) is int and tokens >= 0, "RSI_INVALID_MEASUREMENT")
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT reserved,day FROM rsi_operation_costs WHERE owner=? AND id=? AND state='running'",
                (owner, key),
            ).fetchone()
            require(row is not None, "RSI_OPERATION_CONFLICT")
            db.execute(
                "UPDATE rsi_operation_costs SET state=?,result_json=? WHERE owner=? AND id=? AND state='running'",
                (
                    "completed" if tokens is not None else "unknown",
                    json.dumps(result, allow_nan=False),
                    owner,
                    key,
                ),
            )

    def review_saved(self, owner, cycle_id):
        with self.ledger.connection() as db:
            return {
                r["trial_key"]: json.loads(r["review_json"])
                for r in db.execute(
                    "SELECT * FROM rsi_semantic_reviews WHERE owner=? AND cycle_id=?",
                    (owner, cycle_id),
                )
            }

    def save_review(self, owner, cycle_id, key, value):
        with self.ledger.connection() as db:
            db.execute(
                "INSERT OR IGNORE INTO rsi_semantic_reviews VALUES(?,?,?,?)",
                (owner, cycle_id, key, json.dumps(value)),
            )
