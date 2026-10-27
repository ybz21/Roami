"""Only matching, prior host verification may repair a pipeline issue."""

import json

import pytest

from roami_agent.improvement.issue_verification import for_run
from roami_agent.improvement.run_records import trial_summary
from roami_agent.improvement.status import ImprovementStatus

CONTEXT = {
    key: str(index) * 64
    for index, key in enumerate(("source_hash", "model_hash", "environment_hash", "judge_hash"), 1)
}


def fixture(tmp_path):
    records = ImprovementStatus(tmp_path).runs
    ids = []
    for key, timestamp, passed in (("before", 100, False), ("after", 300, True)):
        ident = records.create(
            "local",
            key,
            "manual",
            {
                "case_ids": ["a"],
                "comparison_context": CONTEXT,
                "context_frozen_ms": timestamp,
            },
        )
        with records.ledger.connection() as db:
            db.execute("UPDATE rsi_pipeline_runs SET created_ms=? WHERE id=?", (timestamp, ident))
        records.case(
            "local",
            ident,
            trial_summary(
                {"id": "a"},
                {"grade": {"passed": passed, "reason": "BROKEN"}, "metrics": {"tokens": 10}},
            ),
        )
        records.observations("local", ident)
        ids.append(ident)
    current = records.get("local", ids[1])
    issue = current["issues"][0]["id"]
    proof = {
        "verified_by": "host_code_verifier_v1",
        "verification_context": CONTEXT,
        "verification_cycles": ["formal", "private"],
        "verified_case_signals": [
            {
                "case_id": "a",
                "case_hash": current["cases"][0]["source_hash"],
                "baseline_signals": ["BROKEN"],
                "candidate_signals": [],
                "issue_ids": [issue],
            }
        ],
    }
    return records, ids, issue, proof


def event(records, proof, timestamp=200, kind="verify.completed"):
    with records.ledger.connection() as db:
        db.execute(
            "INSERT INTO rsi_improvement_events(owner,improvement_id,action_id,event,data_json,created_ms) VALUES('local','item','action',?,?,?)",
            (kind, json.dumps(proof), timestamp),
        )


def test_matching_host_receipt_is_verified_but_not_automatically_closed(tmp_path):
    records, ids, issue, proof = fixture(tmp_path)
    event(records, proof)
    verified, closed, evidence = for_run(records, "local", records.get("local", ids[1]))
    assert verified == [issue] and closed == []
    assert evidence[issue]["verification_cycles"] == ["formal", "private"]
    assert for_run(records, "local", records.get("local", ids[0])) == ([], [], {})


@pytest.mark.parametrize(
    "change",
    [
        "future",
        "source_hash",
        "model_hash",
        "environment_hash",
        "judge_hash",
        "contract",
        "still_present",
        "missing_cycles",
        "executor_claim",
        "malformed",
    ],
)
def test_unrelated_future_or_incomplete_receipts_do_not_verify(tmp_path, change):
    records, ids, _, proof = fixture(tmp_path)
    timestamp = 400 if change == "future" else 200
    if change in CONTEXT:
        proof["verification_context"] = {**CONTEXT, change: "f" * 64}
    elif change == "contract":
        proof["verified_case_signals"][0]["case_hash"] = "f" * 64
    elif change == "still_present":
        proof["verified_case_signals"][0]["candidate_signals"] = ["BROKEN"]
    elif change == "missing_cycles":
        proof["verification_cycles"] = ["formal"]
    elif change == "executor_claim":
        proof["verified_by"] = "codex"
    elif change == "malformed":
        proof["verified_case_signals"] = [{"case_id": "a"}]
    event(records, proof, timestamp)
    assert for_run(records, "local", records.get("local", ids[1])) == ([], [], {})


def test_recurrence_invalidates_an_older_receipt(tmp_path):
    records, ids, _, proof = fixture(tmp_path)
    event(records, proof, 50)
    assert for_run(records, "local", records.get("local", ids[1])) == ([], [], {})


def test_closure_requires_actual_host_observation_for_the_matching_context(tmp_path):
    records, ids, issue, proof = fixture(tmp_path)
    event(records, proof)
    manifest = {
        "source_builds": {"candidate": CONTEXT["source_hash"]},
        "model_hash": CONTEXT["model_hash"],
        "judge_hash": CONTEXT["judge_hash"],
        "machine": {"environment_hash": CONTEXT["environment_hash"]},
    }
    with records.ledger.connection() as db:
        db.execute(
            "INSERT INTO rsi_cycles VALUES('observed','local','day','completed',250,260,260,?,NULL)",
            (json.dumps(manifest),),
        )
    event(records, {"cycle_id": "observed"}, 270, "observation.closed_fixed")
    assert for_run(records, "local", records.get("local", ids[1]))[:2] == ([issue], [issue])
    event(records, {}, 280, "observation.reopened")
    assert for_run(records, "local", records.get("local", ids[1]))[:2] == ([issue], [])
