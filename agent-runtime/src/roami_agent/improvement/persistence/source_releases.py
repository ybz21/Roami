"""Owner-scoped transactional persistence for source releases."""

import json
from datetime import date

from roami_agent.improvement.domain.contracts import require


def active_release(workflow, owner):
    with workflow.ledger.connection() as db:
        row = db.execute("SELECT * FROM rsi_code_targets WHERE owner=?", (owner,)).fetchone()
        return {**json.loads(row["release_json"]), "revision": row["revision"]} if row else None


def activate_release(workflow, action, record, current):
    with workflow.ledger.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        workflow._owned_action(db, action)
        prior = db.execute(
            "SELECT revision FROM rsi_code_targets WHERE owner=?", (action["owner"],)
        ).fetchone()
        revision = prior[0] if prior else 0
        require(
            revision == (current["revision"] if current else 0), "RSI_RELEASE_REVISION_CONFLICT"
        )
        db.execute(
            "INSERT INTO rsi_code_targets VALUES(?,?,?) ON CONFLICT(owner) "
            "DO UPDATE SET revision=excluded.revision,release_json=excluded.release_json",
            (action["owner"], revision + 1, json.dumps(record)),
        )
    return revision


def record_observation(workflow, owner, release, cycle_id, cycle, created, passed, settings):
    with workflow.ledger.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute(
            "SELECT revision FROM rsi_code_targets WHERE owner=?", (owner,)
        ).fetchone()
        require(current and current[0] == release["revision"], "RSI_RELEASE_REVISION_CONFLICT")
        db.execute(
            "INSERT OR IGNORE INTO rsi_code_observations VALUES(?,?,?,?,?)",
            (owner, release["improvement_id"], cycle_id, cycle["day"], int(passed)),
        )
        days = [
            r[0]
            for r in db.execute(
                "SELECT DISTINCT o.day FROM rsi_code_observations o JOIN rsi_cycles c ON c.id=o.cycle_id AND c.owner=o.owner WHERE o.owner=? "
                "AND o.improvement_id=? AND o.passed=1 AND o.day>? AND json_extract(c.manifest_json,'$.source_builds.candidate')=? ORDER BY o.day",
                (owner, release["improvement_id"], created[0], release["candidate_build_hash"]),
            )
        ]
        if not passed:
            previous = release["previous"]
            if previous:
                db.execute(
                    "UPDATE rsi_code_targets SET revision=revision+1,release_json=? WHERE owner=?",
                    (json.dumps(previous), owner),
                )
            else:
                db.execute("DELETE FROM rsi_code_targets WHERE owner=?", (owner,))
            state = "reopened"
            attempt = release.get("attempt", 1) + 1
            followup = workflow._enqueue(
                db,
                owner,
                "repair",
                release["improvement_id"] + ":" + str(attempt),
                {
                    **{k: release[k] for k in ("issue", "point_id") if k in release},
                    "improvement_id": release["improvement_id"],
                    "attempt": attempt,
                    "finding": {**release["finding"], "regression_cycle_id": cycle_id},
                },
            )
            if attempt > settings["max_attempts"]:
                db.execute(
                    "UPDATE rsi_actions SET state='blocked',error_code='RSI_REPAIR_ATTEMPTS_EXHAUSTED' WHERE id=? AND state='queued'",
                    (followup,),
                )
        else:
            consecutive = 0
            previous_day = None
            for day in reversed(days):
                if previous_day is not None and (previous_day - date.fromisoformat(day)).days != 1:
                    break
                consecutive += 1
                previous_day = date.fromisoformat(day)
            state = "closed_fixed" if consecutive >= settings["observation_days"] else "observing"
        db.execute(
            "UPDATE rsi_improvements SET state=?,revision=revision+1,updated_ms=? WHERE id=? AND owner=?",
            (state, workflow.clock(), release["improvement_id"], owner),
        )
        db.execute(
            "INSERT INTO rsi_improvement_events(owner,improvement_id,action_id,event,data_json,created_ms) "
            "VALUES(?,?,?,?,?,?)",
            (
                owner,
                release["improvement_id"],
                cycle_id,
                "observation." + state,
                json.dumps({"cycle_id": cycle_id, "days": days, "passed": bool(passed)}),
                workflow.clock(),
            ),
        )
    return state, days


def verification_day(workflow, release):
    with workflow.ledger.connection() as db:
        created = db.execute(
            "SELECT day FROM rsi_cycles WHERE id=?", (release["verification_cycles"][0],)
        ).fetchone()
    return created


def improvement_state(workflow, owner, release):
    with workflow.ledger.connection() as db:
        item = db.execute(
            "SELECT state FROM rsi_improvements WHERE owner=? AND id=?",
            (owner, release["improvement_id"]),
        ).fetchone()
    return item


def source_target(workflow, owner):
    with workflow.ledger.connection() as db:
        current = db.execute(
            "SELECT release_json FROM rsi_code_targets WHERE owner=?", (owner,)
        ).fetchone()
    return current
