"""Paired comparisons never reward fast failures or incomplete usage."""

import random
import statistics
from collections import defaultdict

from roami_agent.improvement.domain.admission_blocking import blocking_code
from roami_agent.improvement.domain.contracts import require


def percentile(values, fraction):
    values = sorted(values)
    return values[min(len(values) - 1, int((len(values) - 1) * fraction))]


def paired_interval(clusters, *, seed=20261023, repeats=2000):
    random_ = random.Random(seed)
    means = [statistics.mean(v) for v in clusters.values()]
    if len(means) < 2:
        return None
    samples = [statistics.mean(random_.choices(means, k=len(means))) for _ in range(repeats)]
    return [percentile(samples, 0.025), percentile(samples, 0.975)]


def compare(baseline, candidate):
    def index(trials):
        result = {}
        for trial in trials:
            key = (trial["case_id"], trial.get("machine_hash"), trial.get("repetition", 0))
            require(key not in result, "RSI_DUPLICATE_PAIR")
            result[key] = trial
        return result

    left, right = index(baseline), index(candidate)
    require(bool(left) and left.keys() == right.keys(), "RSI_UNPAIRED_TRIALS")
    quality, delivery = defaultdict(list), defaultdict(list)
    hidden_quality, hidden_delivery = defaultdict(list), defaultdict(list)
    paired_time, paired_tokens = [], []
    hidden_time, hidden_tokens = [], []
    regressions, blockers, pending = [], [], []
    measured, admission_blocked = [], []
    groups = defaultdict(list)
    for key in sorted(left):
        a, b = left[key], right[key]
        for field in (
            "case_hash",
            "machine_hash",
            "model_hash",
            "cache_mode",
            "layer",
            "split",
            "cluster",
        ):
            require(
                a.get(field) == b.get(field) and a.get(field) is not None, "RSI_INCOMPARABLE_TRIALS"
            )
        blockers.extend(a.get("release_blockers", []))
        blockers.extend(b.get("release_blockers", []))
        if blocking_code(a) or blocking_code(b):
            admission_blocked.append(a["case_id"])
            blockers.append("admission_blocked")
            continue
        measured.append(key)
        cluster = a["cluster"]
        ga, gb = a["grade"], b["grade"]
        quality[cluster].append(gb["quality"] - ga["quality"])
        da, db = bool(a.get("verified_delivery")), bool(b.get("verified_delivery"))
        delivery[cluster].append(int(db) - int(da))
        if a["split"] == "holdout":
            hidden_quality[cluster].append(gb["quality"] - ga["quality"])
            hidden_delivery[cluster].append(int(db) - int(da))
        if ga["passed"] and not gb["passed"]:
            regressions.append(a["case_id"])
        if ga.get("pending") or gb.get("pending"):
            pending.append(a["case_id"])
        if da and db:
            ma, mb = a["metrics"], b["metrics"]
            if ma.get("elapsed_ms", 0) > 0 and mb.get("elapsed_ms", 0) > 0:
                paired_time.append(mb["elapsed_ms"] / ma["elapsed_ms"])
                if a["split"] == "holdout":
                    hidden_time.append(paired_time[-1])
            if (ma.get("tokens") or 0) > 0 and mb.get("tokens") is not None:
                paired_tokens.append(mb["tokens"] / ma["tokens"])
                if a["split"] == "holdout":
                    hidden_tokens.append(paired_tokens[-1])
        groups[(a["layer"], a.get("category", "unknown"))].append((ga["passed"], gb["passed"]))
    q_ci, d_ci = paired_interval(quality), paired_interval(delivery)
    q_delta = statistics.mean(statistics.mean(v) for v in quality.values()) if quality else None
    time_ratio = statistics.median(paired_time) if paired_time else None
    token_ratio = statistics.median(paired_tokens) if paired_tokens else None
    common_deliveries = sum(
        bool(left[k].get("verified_delivery") and right[k].get("verified_delivery"))
        for k in measured
    )
    all_deliveries_measured = (
        common_deliveries > 0
        and len(paired_time) == common_deliveries
        and len(paired_tokens) == common_deliveries
    )
    observed = [left[k] for k in measured]
    hidden = {a["cluster"] for a in observed if a["split"] == "holdout"}
    validation = {a["cluster"] for a in observed if a["split"] == "validation"}
    exposed = {a["cluster"] for a in observed if a["split"] in {"development", "public_test"}}
    hidden_q_ci = paired_interval(hidden_quality)
    hidden_d_ci = paired_interval(hidden_delivery)
    hidden_q_delta = (
        statistics.mean(statistics.mean(v) for v in hidden_quality.values())
        if hidden_quality
        else None
    )
    hidden_time_ratio = statistics.median(hidden_time) if hidden_time else None
    hidden_token_ratio = statistics.median(hidden_tokens) if hidden_tokens else None
    reasons = []
    if admission_blocked:
        reasons.append("admission_blocked_pairs")
    if regressions:
        reasons.append("baseline_pass_regressed")
    if pending:
        reasons.append("judge_pending")
    if blockers:
        reasons.append("release_blocker")
    if len(hidden) < 30:
        reasons.append("need_30_independent_private_holdout_pairs")
    if len(validation) < 24:
        reasons.append("need_24_private_validation_pairs")
    if hidden & validation:
        reasons.append("validation_holdout_cluster_overlap")
    if hidden & exposed:
        reasons.append("development_holdout_cluster_overlap")
    if hidden_q_ci is None or hidden_q_ci[0] < -1 or hidden_d_ci is None or hidden_d_ci[0] < -0.02:
        reasons.append("quality_noninferiority_unproven")
    if not all_deliveries_measured:
        reasons.append("incomplete_success_efficiency_pairs")
    if (
        time_ratio is not None
        and time_ratio > 1.05
        or token_ratio is not None
        and token_ratio > 1.05
    ):
        reasons.append("efficiency_regression_over_5_percent")
    if not (
        hidden_q_delta is not None
        and hidden_q_delta >= 3
        or hidden_time_ratio is not None
        and hidden_time_ratio <= 0.9
        or hidden_token_ratio is not None
        and hidden_token_ratio <= 0.9
    ):
        reasons.append("no_material_gain")
    return {
        "pairs": len(measured),
        "recorded_pairs": len(left),
        "admission_blocked_cases": admission_blocked,
        "independent_clusters": len(quality),
        "private_holdout_clusters": len(hidden),
        "private_validation_clusters": len(validation),
        "holdout_quality_delta_95ci": hidden_q_ci,
        "holdout_delivery_delta_95ci": hidden_d_ci,
        "holdout_paired_elapsed_ratio_p50": hidden_time_ratio,
        "holdout_paired_token_ratio_p50": hidden_token_ratio,
        "quality_delta": q_delta,
        "quality_delta_95ci": q_ci,
        "delivery_delta_95ci": d_ci,
        "paired_elapsed_ratio_p50": time_ratio,
        "paired_success_token_ratio_p50": token_ratio,
        "efficiency_pairs": {"elapsed": len(paired_time), "tokens": len(paired_tokens)},
        "baseline_pass_regressions": regressions,
        "release_blockers": sorted(set(blockers)),
        "eligible_for_promotion": not reasons,
        "reasons": reasons,
        "strata": [
            {
                "layer": layer,
                "category": category,
                "n": len(values),
                "baseline_passes": sum(a for a, _ in values),
                "candidate_passes": sum(b for _, b in values),
            }
            for (layer, category), values in sorted(groups.items())
        ],
        "p95": None,
        "p95_note": "Requires at least 100 comparable samples per stratum.",
        "interpretation": "Local paired subset; not an official benchmark leaderboard score.",
    }
