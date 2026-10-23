"""Code releases target only the dedicated RSI runner; observation gates close items."""

import json
from datetime import date

from roami_agent.improvement.candidate_checks import checked_evidence, problem_improved
from roami_agent.improvement.contracts import digest, require
from roami_agent.improvement.source_revision import allowed, source_hash


def active_code(workflow, owner):
    with workflow.ledger.connection() as db:
        row = db.execute("SELECT * FROM rsi_code_targets WHERE owner=?", (owner,)).fetchone()
        return {**json.loads(row["release_json"]), "revision": row["revision"]} if row else None


async def activate_code(workflow, action, revisions, config):
    candidate = action["payload"]
    require(all(allowed(p, config) for p in candidate["paths"]), "RSI_PROTECTED_SOURCE")
    item_id = candidate.get("improvement_id", action["subject"])
    builds = {arm: candidate[arm + "_build_hash"] for arm in ("baseline", "candidate")}
    comparison = checked_evidence(
        workflow.ledger, action["owner"], candidate["verification_cycles"], builds
    )
    require(comparison["eligible_for_promotion"], "RSI_PROMOTION_REJECTED")
    current = active_code(workflow, action["owner"])
    if current and current.get("improvement_id") == item_id:
        return current
    require(
        (current["commit"] if current else config["base_commit"]) == candidate["parent_commit"],
        "RSI_SOURCE_BASE_CHANGED",
    )
    require(
        source_hash(candidate["candidate_root"]) == candidate["candidate_build_hash"],
        "RSI_SOURCE_CHANGED",
    )
    sealed = await revisions.seal(candidate)
    # No production process is restarted: this binding is consumed only by the RSI worker.
    record = {
        **sealed,
        "improvement_id": item_id,
        "target": "rsi_runner",
        "applied_ms": workflow.clock(),
        "previous": current,
        "release_id": digest([action["id"], sealed["commit"]]),
    }
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
    return {**record, "revision": revision + 1}


def observe_code(workflow, owner, cycle_id):
    release = active_code(workflow, owner)
    if not release:
        return None
    cycle = workflow.ledger.get(owner, cycle_id)
    with workflow.ledger.connection() as db:
        item = db.execute(
            "SELECT state FROM rsi_improvements WHERE owner=? AND id=?",
            (owner, release["improvement_id"]),
        ).fetchone()
    if not item or item[0] not in {"observing", "closed_fixed"}:
        return None
    require(cycle["state"] == "completed", "RSI_EVIDENCE_INCOMPLETE")
    if (
        not cycle["manifest"].get("formal_daily_suite")
        or cycle["manifest"].get("source_builds", {}).get("candidate")
        != release["candidate_build_hash"]
    ):
        return None
    if cycle["manifest"].get("request_key") != "daily" or cycle["report"] is None:
        return None
    if cycle["manifest"].get("source_builds", {}).get("baseline") != release["baseline_build_hash"]:
        return None
    with workflow.ledger.connection() as db:
        created = db.execute(
            "SELECT day FROM rsi_cycles WHERE id=?", (release["verification_cycles"][0],)
        ).fetchone()
    if cycle["day"] <= created[0]:
        return None
    verified_manifest = workflow.ledger.get(owner, release["verification_cycles"][0])["manifest"]
    if any(
        cycle["manifest"].get(k) != verified_manifest.get(k) for k in ("model_hash", "suite_hash")
    ):
        return {"state": "observing", "reason": "model_changed"}
    semantic = workflow.review_saved(owner, cycle_id)
    if len(semantic) != 120 or not all(r.get("reviewed") for r in semantic.values()):
        return {"state": "observing", "reason": "semantic_review_incomplete"}
    expected = set(cycle["manifest"]["case_ids"])
    arms = {
        arm: {t["case_id"]: t for t in cycle["trials"] if t["arm"] == arm}
        for arm in ("baseline", "candidate")
    }
    require(
        len(cycle["trials"]) == 120 and all(set(v) == expected for v in arms.values()),
        "RSI_EVIDENCE_INCOMPLETE",
    )
    complete = all(
        t.get("log_review", {}).get("complete")
        and t["metrics"].get("tokens") is not None
        and not t["grade"].get("pending")
        for t in cycle["trials"]
    )
    if not complete:
        return {"state": "observing", "reason": "incomplete_measurements"}
    passed = all(
        (
            not arms["baseline"][case]["grade"]["passed"]
            or arms["candidate"][case]["grade"]["passed"]
        )
        and arms["candidate"][case]["grade"]["quality"]
        >= arms["baseline"][case]["grade"]["quality"]
        for case in expected
    )
    case_id = release["finding"]["case_id"]
    passed = passed and problem_improved(
        release["finding"], arms["baseline"][case_id], arms["candidate"][case_id]
    )
    settings = workflow.settings(owner)
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
    return {"state": state, "observation_days": days, "rollback": not passed}
