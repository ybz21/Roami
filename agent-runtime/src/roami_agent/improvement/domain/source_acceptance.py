"""Independent acceptance gates over caller-supplied trial evidence."""

from roami_agent.improvement.domain.comparison import compare
from roami_agent.improvement.domain.contracts import require


def problem_improved(finding, baseline, candidate):
    if not candidate["grade"]["passed"]:
        return False
    metric = finding.get("acceptance_metric", "tokens")
    if metric == "quality":
        return candidate["grade"]["quality"] > baseline["grade"]["quality"]
    if metric == "repeated_read":

        def count(trial):
            return sum(f["code"] == "repeated_read" for f in trial["log_review"]["findings"])

        return count(candidate) < count(baseline)
    require(metric in {"tokens", "elapsed_ms"}, "RSI_INVALID_ACCEPTANCE")
    a, b = baseline["metrics"].get(metric), candidate["metrics"].get(metric)
    return a is not None and b is not None and a > 0 and b < a


def compare_source_evidence(cycles, builds):
    arms = {"baseline": [], "candidate": []}
    for repetition, cycle in enumerate(cycles):
        require(
            cycle["state"] == "completed" and cycle["manifest"].get("source_builds") == builds,
            "RSI_EVIDENCE_MISMATCH",
        )
        expected = set(cycle["manifest"]["case_ids"])
        require(len(cycle["trials"]) == 2 * len(expected), "RSI_EVIDENCE_INCOMPLETE")
        for arm, arm_trials in arms.items():
            trials = [t for t in cycle["trials"] if t["arm"] == arm]
            require({t["case_id"] for t in trials} == expected, "RSI_EVIDENCE_INCOMPLETE")
            for t in trials:
                require(
                    t.get("agent_build_hash") == builds[arm]
                    and t.get("log_review", {}).get("complete"),
                    "RSI_EVIDENCE_MISMATCH",
                )
                arm_trials.append({**t, "repetition": repetition})
    return compare(arms["baseline"], arms["candidate"])
