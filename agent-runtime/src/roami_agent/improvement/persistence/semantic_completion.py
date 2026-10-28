"""A daily run finishes only after scoring, metering and every semantic review."""

import json

from roami_agent.improvement.domain.contracts import evaluation_arms, require


def complete_cycle_review(db, owner, cycle_id):
    cycle = db.execute(
        "SELECT * FROM rsi_cycles WHERE owner=? AND id=?", (owner, cycle_id)
    ).fetchone()
    require(cycle is not None and cycle["state"] == "completed", "RSI_REVIEW_INCOMPLETE")
    manifest, report = json.loads(cycle["manifest_json"]), json.loads(cycle["report_json"])
    expected = {arm + ":" + c for arm in evaluation_arms(manifest) for c in manifest["case_ids"]}
    reviews = {
        r["trial_key"]: json.loads(r["review_json"])
        for r in db.execute(
            "SELECT * FROM rsi_semantic_reviews WHERE owner=? AND cycle_id=?", (owner, cycle_id)
        )
    }
    require(
        set(reviews) == expected and all(r.get("reviewed") is True for r in reviews.values()),
        "RSI_REVIEW_INCOMPLETE",
    )
    records = list(
        db.execute("SELECT arm,case_id,record_json FROM rsi_trials WHERE cycle_id=?", (cycle_id,))
    )
    trials = [json.loads(r["record_json"]) for r in records]
    resolved = (
        len(trials) == len(expected)
        and {r["arm"] + ":" + r["case_id"] for r in records} == expected
        and all(
            t.get("grade", {}).get("pending") is False
            and type(t.get("metrics", {}).get("tokens")) is int
            and t["metrics"]["tokens"] >= 0
            and t.get("log_review", {}).get("complete") is True
            for t in trials
        )
    )
    report.update(
        semantic_review={"complete": True, "reviewed": len(reviews)},
        evaluation_complete=bool(report.get("full_suite_complete") and resolved),
        daily_complete=bool(
            manifest.get("formal_daily_suite") and report.get("full_suite_complete") and resolved
        ),
        report_phase="reviewed",
    )
    db.execute(
        "UPDATE rsi_cycles SET report_json=? WHERE owner=? AND id=?",
        (json.dumps(report, allow_nan=False), owner, cycle_id),
    )
