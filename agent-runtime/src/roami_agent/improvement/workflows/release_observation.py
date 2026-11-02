"""Code releases target only the dedicated RSI runner; observation gates close items."""

from roami_agent.improvement.domain.contracts import digest, require
from roami_agent.improvement.domain.source_acceptance import problem_improved
from roami_agent.improvement.integrations.source_workspace import allowed, source_hash
from roami_agent.improvement.persistence.source_releases import (
    activate_release,
    active_release,
    improvement_state,
    record_observation,
    verification_day,
)
from roami_agent.improvement.workflows.candidate_checks import checked_evidence


def active_code(workflow, owner):
    return active_release(workflow, owner)


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
    revision = activate_release(workflow, action, record, current)
    return {**record, "revision": revision + 1}


def observe_code(workflow, owner, cycle_id):
    release = active_code(workflow, owner)
    if not release:
        return None
    cycle = workflow.ledger.get(owner, cycle_id)
    item = improvement_state(workflow, owner, release)
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
    created = verification_day(workflow, release)
    if cycle["day"] <= created[0]:
        return None
    verified_manifest = workflow.ledger.get(owner, release["verification_cycles"][0])["manifest"]
    if any(
        cycle["manifest"].get(k) != verified_manifest.get(k) for k in ("model_hash", "suite_hash")
    ):
        return {"state": "observing", "reason": "model_changed"}
    if cycle["manifest"].get("judge_hash") != verified_manifest.get("judge_hash") or cycle[
        "manifest"
    ]["machine"].get("environment_hash") != verified_manifest["machine"].get("environment_hash"):
        return {"state": "observing", "reason": "evaluation_context_changed"}
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
    state, days = record_observation(
        workflow, owner, release, cycle_id, cycle, created, passed, settings
    )
    return {"state": state, "observation_days": days, "rollback": not passed}
