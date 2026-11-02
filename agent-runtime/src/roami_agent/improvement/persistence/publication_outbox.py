"""Owner-scoped transactional persistence for publication outbox."""

import json

from roami_agent.improvement.domain.contracts import require
from roami_agent.protocol.identity import now_ms


def complete_issue_publication(records, owner, run_id, receipt):
    with records.ledger.connection() as db:
        db.execute(
            "INSERT OR REPLACE INTO rsi_pipeline_effects VALUES(?,'completed',?)",
            (run_id, json.dumps(receipt)),
        )
        db.execute(
            "UPDATE rsi_pipeline_runs SET issue_json=?,updated_ms=? WHERE id=? AND owner=?",
            (json.dumps(receipt), now_ms(), run_id, owner),
        )


def reject_unknown_publication(records, owner, run_id):
    with records.ledger.connection() as db:
        require(
            db.execute(
                "INSERT OR IGNORE INTO rsi_pipeline_effects VALUES(?,'started',NULL)",
                (run_id,),
            ).rowcount
            == 1,
            "RSI_PUBLICATION_OUTCOME_UNKNOWN",
        )


def publication_effect(records, run_id):
    with records.ledger.connection() as db:
        effect = db.execute(
            "SELECT * FROM rsi_pipeline_effects WHERE run_id=?", (run_id,)
        ).fetchone()
    return effect
