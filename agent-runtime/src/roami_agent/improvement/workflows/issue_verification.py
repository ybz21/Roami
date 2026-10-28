"""Issue repair receipts come from host verification, never executor completion claims."""

from roami_agent.improvement.domain.contracts import digest
from roami_agent.improvement.persistence.evidence_queries import case_issues, matching_case_signals


def case_signals(ledger, owner, formal, case_id):
    from roami_agent.improvement.evaluation.trial_evidence import trial_summary

    issues = case_issues(ledger, owner, case_id)
    if not issues:
        return []
    arms = {trial["arm"]: trial for trial in formal["trials"] if trial["case_id"] == case_id}
    if set(arms) != {"baseline", "candidate"}:
        return []
    candidate = arms["candidate"]
    if (
        not candidate["grade"].get("passed")
        or candidate["grade"].get("pending")
        or candidate.get("log_review", {}).get("complete") is not True
        or type(candidate.get("metrics", {}).get("tokens")) is not int
    ):
        return []
    observed = {}
    try:
        for arm, trial in arms.items():
            root = ledger.path.parent / "runs" / formal["id"] / (digest(case_id)[:20] + "-" + arm)
            if (
                not any(
                    (root / name).is_file()
                    for name in ("state/execution-log.json", "execution-log.json")
                )
                and trial.get("layer") != "mechanism"
            ):
                return []
            observed[arm] = trial_summary(
                {"id": case_id, "split": trial.get("split"), "layer": trial.get("layer")},
                trial,
                root,
            )["signals"]
    except (OSError, ValueError, KeyError):
        return []
    matched = []
    matching_case_signals(ledger, owner, case_id, issues, candidate, observed, matched)
    return (
        [
            {
                "case_id": case_id,
                "case_hash": candidate["case_hash"],
                "baseline_signals": observed["baseline"],
                "candidate_signals": observed["candidate"],
                "issue_ids": matched,
            }
        ]
        if matched
        else []
    )
