"""Model access failures are incomplete evidence, not agent quality scores."""

MODEL_AUTHENTICATION_BLOCKERS = ("MODEL_HTTP_401", "MODEL_HTTP_403")

# Execution blockers do not imply a request was rejected before dispatch.
MODEL_ADMISSION_BLOCKERS = (
    *MODEL_AUTHENTICATION_BLOCKERS,
    "MODEL_HTTP_402",
    "MODEL_PROXY_USAGE_UNKNOWN",
    "MODEL_PROXY_CURRENCY_MISMATCH",
    "MODEL_PROXY_DAILY_LIMIT",
)


def blocking_code(result, signals=()):
    if result.get("blocked_by"):
        return result["blocked_by"]["code"]
    grade = result.get("grade", {})
    for code in (result.get("admission_error"), result.get("execution_error"), grade.get("reason")):
        if code in MODEL_ADMISSION_BLOCKERS or (
            code == "RSI_USAGE_UNKNOWN" and not result.get("shared_admission_managed")
        ):
            return code
    if not result.get("shared_admission_managed") and set(result.get("release_blockers", [])) & {
        "unknown_provider_usage",
        "unknown_artifact_review_usage",
    }:
        return "RSI_USAGE_UNKNOWN"
    if not grade.get("passed"):
        return next((code for code in MODEL_ADMISSION_BLOCKERS if code in signals), None)
    return None


def blocked_result(cause):
    return {
        "grade": {
            "passed": False,
            "hard_passed": False,
            "pending": False,
            "quality": 0,
            "reason": cause["code"],
        },
        "metrics": {
            "tokens": 0,
            "token_coverage": "complete",
            "model_calls": 0,
            "tool_calls": 0,
            "elapsed_ms": None,
            "model_ms": 0,
            "right_censored": True,
        },
        "execution_kind": "admission_blocked",
        "verified_delivery": False,
        "release_blockers": ["admission_blocked"],
        "blocked_by": dict(cause),
    }
