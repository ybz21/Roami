"""Owner-scoped transactional persistence for evidence queries."""

from pathlib import Path

from roami_agent.improvement.domain.contracts import require
from roami_agent.improvement.evaluation.contracts import load_suite


def verification_suites(workflow, action, candidate, ids, suites):
    with workflow.ledger.connection() as db:
        for suite_id in ids:
            row = db.execute(
                "SELECT * FROM rsi_suites WHERE owner=? AND id=?", (action["owner"], suite_id)
            ).fetchone()
            require(row is not None, "RSI_SUITE_NOT_FOUND")
            value = load_suite(Path(row["path"]))
            require(value["content_hash"] == row["content_hash"], "RSI_SUITE_HASH_MISMATCH")
            suites.append(value)
        origin = db.execute(
            "SELECT manifest_json FROM rsi_cycles WHERE id=? AND owner=?",
            (candidate["finding"]["cycle_id"], action["owner"]),
        ).fetchone()
    return origin


def verification_budget(ledger, owner, day):
    with ledger.connection() as db:
        return db.execute(
            "SELECT * FROM rsi_budgets WHERE owner=? AND day=?", (owner, day)
        ).fetchone()


def matching_case_signals(ledger, owner, case_id, issues, candidate, observed, matched):
    with ledger.connection() as db:
        for issue in issues:
            original = db.execute(
                "SELECT c.source_hash FROM rsi_pipeline_observations o JOIN rsi_pipeline_cases c ON c.run_id=o.run_id AND c.case_id=? JOIN rsi_pipeline_runs r ON r.id=o.run_id WHERE o.issue_id=? AND r.owner=? AND o.status='present' ORDER BY r.created_ms,r.id LIMIT 1",
                (case_id, issue["id"], owner),
            ).fetchone()
            if (
                original
                and original[0] == candidate["case_hash"]
                and issue["code"] in observed["baseline"]
                and issue["code"] not in observed["candidate"]
            ):
                matched.append(issue["id"])


def case_issues(ledger, owner, case_id):
    with ledger.connection() as db:
        issues = db.execute(
            "SELECT id,code FROM rsi_pipeline_issues WHERE owner=? AND case_id=?", (owner, case_id)
        ).fetchall()
    return issues


def issue_observations(workflow, owner):
    with workflow.ledger.connection() as db:
        items = {
            r["id"]: dict(r)
            for r in db.execute(
                "SELECT id,state,data_json FROM rsi_improvements WHERE owner=?", (owner,)
            )
        }
    return items


def suite_source(ledger, owner, suite_id):
    with ledger.connection() as db:
        return db.execute(
            "SELECT path,content_hash FROM rsi_suites WHERE owner=? AND id=?", (owner, suite_id)
        ).fetchone()
