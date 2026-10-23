"""Only bounded context and discovery parameters may enter an experiment."""

from dataclasses import replace

from roami_agent.improvement.contracts import digest, require

BOUNDS = {
    "memory_recall_limit": (1, 16, 8),
    "memory_recall_tokens": (256, 4096, 2000),
    "tool_directory_page_size": (1, 20, 10),
    "keep_recent_tokens": (1024, 64000, 20000),
}


def validate_policy(raw):
    require(isinstance(raw, dict) and set(raw) <= set(BOUNDS), "RSI_POLICY_FIELD_FORBIDDEN")
    for name, value in raw.items():
        lower, upper, _ = BOUNDS[name]
        require(type(value) is int and lower <= value <= upper, "RSI_POLICY_OUT_OF_RANGE")
    return {key: raw.get(key, spec[2]) for key, spec in BOUNDS.items()}


def policy_id(raw):
    return digest(validate_policy(raw))


def apply_policy(settings, raw):
    return replace(settings, **validate_policy(raw))


def propose(policy, trials, *, forbidden_splits=("holdout", "public_test")):
    """One coordinate per proposal keeps measured effects attributable."""
    current = validate_policy(policy)
    require(
        all(t["split"] not in forbidden_splits for t in trials), "RSI_EVALUATION_DATA_READ_ONLY"
    )
    proposals = []
    failures = [t for t in trials if not t.get("grade", {}).get("passed")]
    if failures:
        return [
            {
                "status": "diagnosis_required",
                "case_ids": [t["case_id"] for t in failures],
                "reason": "Fix failed acceptance before reducing context or discovery budgets.",
            }
        ]
    for key, fraction in (
        ("memory_recall_limit", 0.75),
        ("memory_recall_tokens", 0.75),
        ("keep_recent_tokens", 0.8),
        ("tool_directory_page_size", 0.8),
    ):
        value = max(BOUNDS[key][0], int(current[key] * fraction))
        if value != current[key]:
            candidate = dict(current, **{key: value})
            proposals.append(
                {
                    "status": "proposed",
                    "policy": candidate,
                    "policy_id": policy_id(candidate),
                    "changed": key,
                    "reason": "Test a smaller budget with unchanged quality gates.",
                    "evidence_case_ids": [t["case_id"] for t in trials],
                }
            )
    return proposals


def next_candidate(baseline, reports):
    baseline = validate_policy(baseline)
    seen = {policy_id(baseline)}
    for report in reports:
        seen.add(report["candidate_id"])
    queue = [p for report in reversed(reports) for p in report.get("proposals", [])]
    if not reports:
        queue = propose(baseline, [])
    for proposal in queue:
        if proposal.get("status") == "proposed" and proposal["policy_id"] not in seen:
            return validate_policy(proposal["policy"])
    return None
