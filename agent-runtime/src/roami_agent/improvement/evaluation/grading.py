"""Independent assertions and explicit, calibrated human rubric evidence."""

import json
import math
import re

from roami_agent.improvement.domain.contracts import DIMENSIONS, number, require
from roami_agent.improvement.domain.scoring import quality, same_json
from roami_agent.improvement.integrations.artifact_paths import relative_file
from roami_agent.protocol.errors import DomainError


def judge_case(case, output, workspace):
    judge = case["judge"]
    kind = judge["kind"]
    if kind == "gaia_course":
        from roami_agent.improvement.evaluation.benchmarks.gaia_tasks import grade_gaia_course

        return grade_gaia_course(case, workspace)
    if kind == "workbook":
        from roami_agent.improvement.evaluation.benchmarks.spreadsheet import grade_workbook

        return grade_workbook(case, workspace)
    if kind in {
        "external",
        "rubric",
        "terminal",
        "python_contract",
        "vectorization",
        "media",
        "swe",
        "slides",
        "long_memory",
        "company",
        "company_stock",
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
        all(
            isinstance(r, dict) and isinstance(r.get("rater"), str) and bool(r["rater"])
            for r in ratings
        )
    )
    require(
        len({r.get("rater") for r in ratings}) == 2 and all(r.get("blind") is True for r in ratings)
    )
    for rating in ratings:
        require(
            isinstance(rating.get("dimensions"), dict)
            and set(rating["dimensions"]) == set(DIMENSIONS)
        )
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
