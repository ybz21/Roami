"""Bounded native scores for case details and reports, without hidden grader inputs."""

import re

from roami_agent.improvement.domain.contracts import number


def _score_fields(grade):
    evidence = {
        key: grade[key]
        for key in ("native_metric", "native_metric_minimum")
        if number(grade.get(key), 0, 1)
    }
    references = grade.get("native_reference_results")
    if (
        isinstance(references, list)
        and 1 <= len(references) <= 8
        and all(number(value, 0, 1) for value in references)
    ):
        evidence["native_reference_results"] = list(references)
    partial = grade.get("native_partial")
    keys = {"scored_points", "total_points", "unscored_points"}
    if (
        isinstance(partial, dict)
        and keys <= set(partial)
        and all(
            type(partial[key]) is int and 0 <= partial[key] <= 1_000_000
            for key in ("total_points", "unscored_points")
        )
        and 0 < partial["total_points"]
        and (
            partial["scored_points"] is None
            and partial["unscored_points"] == partial["total_points"]
            or type(partial["scored_points"]) is int
            and 0 <= partial["scored_points"]
            and partial["scored_points"] + partial["unscored_points"] <= partial["total_points"]
        )
    ):
        evidence["native_partial"] = {key: partial[key] for key in sorted(keys)}
    if not evidence:
        return evidence
    scope = grade.get("grade_scope")
    if isinstance(scope, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,159}", scope):
        evidence["grade_scope"] = scope
    checksum = grade.get("native_result_sha256")
    if isinstance(checksum, str) and re.fullmatch(r"[a-f0-9]{64}", checksum):
        evidence["native_result_sha256"] = checksum
    official = grade.get("official_leaderboard_comparable")
    if type(official) is bool:
        evidence["official_leaderboard_comparable"] = official
    if type(grade.get("native_verifier_ran")) is bool:
        evidence["native_verifier_ran"] = grade["native_verifier_ran"]
    return evidence


def native_judgment(grade):
    evidence = _score_fields(grade)
    if not evidence:
        return evidence
    checks = grade.get("checks", {})
    if grade.get("grade_scope") == "original_media_verifier_plus_frozen_delivery_checks":
        ran = (
            checks.get("verifier_exited") is True
            and checks.get("verifier_result_valid") is not False
        )
        evidence["native_verifier_ran"] = ran
        if not ran:
            evidence.pop("native_metric", None)
    if "native_reference_match" not in checks:
        evidence.pop("native_reference_results", None)
    return evidence


def report_judgments(cases):
    rows = []
    for case in cases:
        arms = case.get("arm_results") or {None: case}
        for arm, outcome in arms.items():
            evidence = _score_fields(outcome.get("native_judgment", {}))
            if evidence:
                rows.append(
                    {"case_id": case["case_id"], **({"arm": arm} if arm else {}), **evidence}
                )
    return rows
