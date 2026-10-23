"""Independent assertions and explicit, calibrated human rubric evidence."""

import json
import math
import re

from roami_agent.improvement.contracts import DIMENSIONS, number, relative_file, require
from roami_agent.protocol.errors import DomainError

POINTS = (0, 25, 50, 80, 100)
PROFILES = {
    "coding": (0.45, 0.20, 0.25, 0.10),
    "engineering": (0.40, 0.25, 0.20, 0.15),
    "presentation": (0.30, 0.25, 0.35, 0.10),
    "demo": (0.35, 0.25, 0.30, 0.10),
    "media": (0.30, 0.20, 0.40, 0.10),
    "research": (0.40, 0.20, 0.15, 0.25),
    "finance_research": (0.40, 0.20, 0.15, 0.25),
    "analysis": (0.45, 0.20, 0.20, 0.15),
    "quant": (0.45, 0.20, 0.20, 0.15),
    "experiment": (0.35, 0.25, 0.25, 0.15),
    "mechanism": (0.40, 0.25, 0.20, 0.15),
}


def same_json(actual, expected):
    if type(actual) is bool or type(expected) is bool:
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            same_json(actual[k], expected[k]) for k in actual
        )
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(
            same_json(a, b) for a, b in zip(actual, expected, strict=True)
        )
    return actual == expected


def quality(dimensions, profile="mechanism", *, hard_passed, pending=False):
    require(profile in PROFILES, "RSI_UNKNOWN_PROFILE")
    require(set(dimensions) == set(DIMENSIONS))
    require(all(type(v) is int and 0 <= v <= 4 for v in dimensions.values()))
    score = sum(
        POINTS[dimensions[key]] * weight
        for key, weight in zip(DIMENSIONS, PROFILES[profile], strict=True)
    )
    return {
        "dimensions": dimensions,
        "quality": round(score, 6) if hard_passed else 0,
        "hard_passed": hard_passed,
        "pending": pending,
        "passed": bool(
            hard_passed and not pending and min(dimensions.values()) >= 3 and score >= 80 - 1e-9
        ),
    }


def judge_case(case, output, workspace):
    judge = case["judge"]
    kind = judge["kind"]
    if kind == "workbook":
        from roami_agent.improvement.spreadsheet import grade_workbook

        return grade_workbook(case, workspace)
    if kind in {
        "external",
        "rubric",
        "terminal",
        "python_contract",
        "vectorization",
        "media",
        "swe",
    }:
        return {
            **quality(dict.fromkeys(DIMENSIONS, 0), hard_passed=True, pending=True),
            "reason": "independent_judge_required",
        }
    text = output
    try:
        if "path" in judge:
            path = relative_file(workspace, judge["path"])
            require(path.is_file() and path.stat().st_size <= 2_000_000)
            text = path.read_text()
        if kind == "numeric":
            # Explanations are not parsed for a convenient matching number.
            match = re.fullmatch(
                r"\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*%?\s*", text
            )
            value = float(match[1]) if match else math.nan
            passed = math.isfinite(value) and abs(value - judge["expected"]) <= judge.get(
                "tolerance", 0.0001
            )
        else:
            actual = json.loads(text)
            passed = same_json(actual, judge["expected"])
    except (OSError, ValueError, UnicodeError, DomainError):
        passed = False
    result = quality(
        dict.fromkeys(DIMENSIONS, 3 if passed else 0),
        case.get("grading_profile", "mechanism"),
        hard_passed=passed,
    )
    result.update(
        judge_kind=kind,
        grade_scope="objective_contract",
        native_metric=float(passed),
        reason="assertions_passed" if passed else "assertion_failed",
    )
    return result


def calibrated_grade(case, ratings, *, hard_passed, calibration_id):
    require(isinstance(calibration_id, str) and bool(calibration_id))
    require(isinstance(ratings, list) and len(ratings) == 2)
    require(
        len({r.get("rater") for r in ratings}) == 2 and all(r.get("blind") is True for r in ratings)
    )
    require(all(isinstance(r.get("rater"), str) and bool(r["rater"]) for r in ratings))
    for rating in ratings:
        require(set(rating["dimensions"]) == set(DIMENSIONS))
        require(all(type(v) is int and 0 <= v <= 4 for v in rating["dimensions"].values()))
    dimensions = {key: min(r["dimensions"][key] for r in ratings) for key in DIMENSIONS}
    disputed = any(
        abs(ratings[0]["dimensions"][key] - ratings[1]["dimensions"][key]) > 1
        or (ratings[0]["dimensions"][key] >= 3) != (ratings[1]["dimensions"][key] >= 3)
        for key in DIMENSIONS
    )
    require(
        all(v < 4 or key in case.get("excellence_dimensions", []) for key, v in dimensions.items()),
        "RSI_UNREGISTERED_EXCELLENCE",
    )
    result = quality(
        dimensions,
        case.get("grading_profile", "mechanism"),
        hard_passed=hard_passed,
        pending=disputed,
    )
    result.update(
        calibration_id=calibration_id,
        reason="human_review_required" if disputed else "blind_rubric",
    )
    return result


def validate_external_grade(grade):
    require(isinstance(grade, dict) and type(grade.get("hard_passed")) is bool)
    require(type(grade.get("pending")) is bool)
    require(number(grade.get("native_metric"), 0, 1))
    # Native verifiers establish objective pass, never visual excellence by themselves.
    passed = grade["hard_passed"] and grade["native_metric"] == 1
    return {
        **quality(
            dict.fromkeys(DIMENSIONS, 3 if passed else 0),
            hard_passed=passed,
            pending=grade["pending"],
        ),
        "native_metric": grade["native_metric"],
        "grade_scope": "native_objective_contract",
    }
