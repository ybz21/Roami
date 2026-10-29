"""Default issue severity before an evidence-backed review overrides it."""


def issue_priority(code):
    if code in {"RSI_UNEXPECTED_MODEL_TOOL", "RSI_PRIVATE_OUTPUT_REQUIRED"}:
        return "P0", "boundary_violation"
    if code in {
        "RSI_NATIVE_TASK_FAILED",
        "MODEL_OUTPUT_LENGTH",
        "RSI_NATIVE_TASK_REQUIRED",
        "MODEL_HTTP_401",
        "MODEL_HTTP_403",
    }:
        return "P1", "delivery_blocked"
    return "P2", "review_required"
