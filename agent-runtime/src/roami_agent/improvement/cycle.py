"""Budgeted daily A/B cycles with frozen inputs and an auditable proposal queue."""

import asyncio
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from roami_agent.improvement.behavior_review import review_cycle, review_trial
from roami_agent.improvement.comparison import compare
from roami_agent.improvement.contracts import (
    VERSION,
    digest,
    implementation_hash,
    require,
    validate_suite,
)
from roami_agent.improvement.daily_suite import daily_coverage
from roami_agent.improvement.executors import private_json
from roami_agent.improvement.policy import policy_id, propose, validate_policy
from roami_agent.protocol.errors import DomainError


def daily_selection(cases, day, *, limit, seed):
    """Order strata and cases independently of observed performance."""
    require(type(limit) is int and 1 <= limit <= 1000)
    groups = defaultdict(list)
    for case in cases:
        groups[(case["layer"], case["category"])].append(case)
    random_ = random.Random(digest([seed, day]))
    keys = sorted(groups)
    random_.shuffle(keys)
    for key in keys:
        groups[key].sort(key=lambda c: c["id"])
        random_.shuffle(groups[key])
    selected = []
    while keys and len(selected) < limit:
        for key in list(keys):
            selected.append(groups[key].pop())
            if not groups[key]:
                keys.remove(key)
            if len(selected) == limit:
                break
    return selected


async def run_cycle(
    *,
    ledger,
    owner,
    day,
    suite,
    machine,
    executor,
    baseline,
    candidate,
    output_root,
    daily_tokens,
    daily_episodes,
    case_limit=None,
    seed=20261023,
    request_key="daily",
    schedule_period=None,
    period_machines=None,
    source_builds=None,
    paired=True,
):
    validate_suite(suite)
    baseline = validate_policy(baseline)
    candidate = validate_policy({**baseline, **candidate})
    if source_builds is not None:
        require(set(source_builds) == {"baseline", "candidate"})
        require(all(isinstance(v, str) and len(v) == 64 for v in source_builds.values()))
        require(callable(getattr(executor, "run_arm", None)), "RSI_CODE_EXECUTOR_REQUIRED")
    require(type(paired) is bool)
    require(
        paired
        or baseline == candidate
        and (source_builds is None or source_builds["baseline"] == source_builds["candidate"]),
        "RSI_COMPARISON_REQUIRED",
    )
    trial_arms = ["baseline", "candidate"] if paired else ["baseline"]
    require(machine.get("cache_mode") in {"cold", "warm", "uncontrolled"})
    require(
        isinstance(machine.get("environment_hash"), str) and len(machine["environment_hash"]) == 64,
        "RSI_MACHINE_FINGERPRINT_REQUIRED",
    )
    # Uncontrolled cache comparisons may be diagnostic, never release evidence.
    require(case_limit is None or case_limit >= len(suite["cases"]), "RSI_FULL_SUITE_REQUIRED")
    cases = daily_selection(suite["cases"], day, limit=len(suite["cases"]), seed=seed)
    reservation = getattr(executor, "reservation_tokens", lambda case: case["limits"]["tokens"])
    costs = {case["id"]: reservation(case) for case in cases}
    require(all(type(cost) is int and cost >= 0 for cost in costs.values()))
    tokens = len(trial_arms) * sum(costs.values())
    require(
        tokens <= daily_tokens and len(trial_arms) * len(cases) <= daily_episodes,
        "RSI_FULL_SUITE_BUDGET",
    )
    manifest = {
        "schedule_period": schedule_period,
        "period_machines": period_machines,
        "runner_version": VERSION,
        "request_key": request_key,
        "implementation_hash": implementation_hash(),
        "standard_version": "rsi-v1.7-single-baseline-daily-20261023",
        "suite_id": suite["id"],
        "suite_hash": suite["content_hash"],
        "case_hashes": {c["id"]: digest(c) for c in cases},
        "case_ids": [c["id"] for c in cases],
        "coverage_mode": "full_suite",
        "expected_cases": len(cases),
        "review_required": True,
        "formal_daily_suite": daily_coverage(suite)["complete"],
        "daily_coverage": daily_coverage(suite),
        "machine": machine,
        "model_hash": executor.model_hash,
        "baseline_policy": baseline,
        "candidate_policy": candidate,
        "baseline_id": policy_id(baseline),
        "candidate_id": policy_id(candidate),
        "experiment_kind": "policy_comparison"
        if policy_id(candidate) != policy_id(baseline)
        else "baseline_stability",
        "seed": seed,
        "reserved_tokens": tokens,
        "reserved_episodes": len(trial_arms) * len(cases),
        "trial_arms": trial_arms,
    }
    if source_builds is not None:
        manifest["source_builds"] = source_builds
        manifest["experiment_kind"] = "source_comparison"
    cycle_id, admitted = await asyncio.to_thread(
        ledger.reserve,
        owner,
        day,
        manifest,
        tokens_limit=daily_tokens,
        episodes_limit=daily_episodes,
    )
    if not admitted:
        return {"cycle_id": cycle_id, "admitted": False, "reason": "already_recorded_no_replay"}
    cycle_root = Path(output_root) / cycle_id
    cycle_root.mkdir(parents=True, mode=0o700)
    private_json(cycle_root / "manifest.json", manifest)
    private_json(cycle_root / "suite.json", suite)
    trials = {arm: [] for arm in trial_arms}
    try:
        for case in cases:
            # Order is balanced without learning the verifier or looking at either result.
            arms = list(trial_arms)
            random.Random(digest([seed, day, case["id"]])).shuffle(arms)
            for arm in arms:
                root = cycle_root / (digest(case["id"])[:20] + "-" + arm)
                root.mkdir(mode=0o700)
                try:
                    if source_builds is not None:
                        result = await executor.run_arm(
                            arm, case, baseline if arm == "baseline" else candidate, root
                        )
                    else:
                        result = await executor.run(
                            case, baseline if arm == "baseline" else candidate, root
                        )
                except (DomainError, OSError, TimeoutError, ValueError) as error:
                    result = {
                        "grade": {
                            "passed": False,
                            "quality": 0,
                            "hard_passed": False,
                            "pending": False,
                            "reason": error.code
                            if isinstance(error, DomainError)
                            else "RSI_WORKER_ERROR",
                        },
                        "metrics": {"tokens": None, "elapsed_ms": None, "right_censored": True},
                        "verified_delivery": False,
                        "release_blockers": ["worker_error"],
                    }
                trial = {
                    "case_id": case["id"],
                    "case_hash": digest(case),
                    "cluster": case.get("cluster", case["id"]),
                    "category": case["category"],
                    "layer": case["layer"],
                    "split": case["split"],
                    "counts_as_delivery": case["counts_as_delivery"],
                    "repetition": 0,
                    "machine_hash": digest(machine),
                    "model_hash": executor.model_hash,
                    "cache_mode": machine["cache_mode"],
                    "policy_id": manifest[arm + "_id"],
                    **result,
                }
                if source_builds is not None:
                    trial["agent_build_hash"] = source_builds[arm]
                if machine["cache_mode"] == "uncontrolled":
                    trial["release_blockers"].append("cache_uncontrolled")
                if manifest["baseline_id"] == manifest["candidate_id"] and (
                    source_builds is None or source_builds["baseline"] == source_builds["candidate"]
                ):
                    trial["release_blockers"].append("no_policy_change")
                trial["log_review"] = await asyncio.to_thread(review_trial, trial, root)
                if not trial["log_review"]["complete"]:
                    trial["release_blockers"].append("execution_logs_missing")
                # Full outputs stay in the private trial file, outside the optimizer's proposal view.
                private_json(root / "trial.json", trial)
                await asyncio.to_thread(ledger.append, owner, cycle_id, arm, trial)
                trials[arm].append(trial)
        comparison = (
            compare(trials["baseline"], trials["candidate"])
            if paired
            else {
                "pairs": 0,
                "eligible_for_promotion": False,
                "reasons": ["quality_noninferiority_unproven"],
                "release_blockers": ["baseline_observation_only"],
            }
        )
        review = review_cycle(manifest, trials)
        private_json(cycle_root / "review.json", review)
        development = [
            t
            for t in trials.get("candidate", trials["baseline"])
            if t["split"] == "development" and t["layer"] != "smoke"
        ]
        proposals = propose(candidate, development) if development else []
        report = {
            "cycle_id": cycle_id,
            "suite_hash": suite["content_hash"],
            "machine_hash": digest(machine),
            "model_hash": executor.model_hash,
            "candidate_id": manifest["candidate_id"],
            "experiment_kind": manifest["experiment_kind"],
            "implementation_hash": manifest["implementation_hash"],
            "budget_omitted_case_ids": [],
            "runner_version": VERSION,
            "comparison": comparison,
            "coverage": review["coverage"],
            "review": review["summary"],
            "full_suite_complete": review["summary"]["complete"],
            "evaluation_complete": review["summary"]["complete"]
            and all(
                t["grade"].get("pending") is False
                and type(t["metrics"].get("tokens")) is int
                and t["metrics"]["tokens"] >= 0
                for items in trials.values()
                for t in items
            ),
            "daily_complete": False,
            "report_phase": "evaluated_waiting_semantic_review",
            "counts": {
                arm: {
                    "executed": len(items),
                    "passed": sum(t["grade"]["passed"] for t in items),
                    "verified_deliveries": sum(t["verified_delivery"] for t in items),
                }
                for arm, items in trials.items()
            },
            "proposals": proposals,
            "policy_applied_to_live_agent": False,
            "reservation_note": "Worst-case daily reservation retained, including interrupted/unknown calls.",
        }
        private_json(cycle_root / "report.json", report)
        await asyncio.to_thread(ledger.finish, owner, cycle_id, report)
        return {"admitted": True, **report}
    except BaseException:
        review = review_cycle(manifest, trials)
        private_json(cycle_root / "interrupted-review.json", review)
        await asyncio.to_thread(
            ledger.finish,
            owner,
            cycle_id,
            {
                "reason": "cycle_interrupted",
                "usage_known": False,
                "daily_complete": False,
                "coverage": review["coverage"],
                "review": review["summary"],
            },
            state="interrupted",
        )
        raise


async def watch(run, *, timezone="Asia/Shanghai", hour=3, stop=None, sleep=asyncio.sleep):
    require(type(hour) is int and 0 <= hour <= 23)
    zone = ZoneInfo(timezone)
    last_day = None
    while stop is None or not stop.is_set():
        now = datetime.now(zone)
        day = now.date().isoformat()
        if now.hour >= hour and day != last_day:
            await run(day)
            last_day = day
        await sleep(30)
