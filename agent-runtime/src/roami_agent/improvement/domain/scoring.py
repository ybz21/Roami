"""Pure objective-score and JSON comparison rules."""

from roami_agent.improvement.domain.contracts import DIMENSIONS, require

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
