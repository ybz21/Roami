"""Per-attempt wall-clock facts; absent deadlines never become runtime limits."""


def execution_timing(turn, observed_ms):
    started = turn.get("executionStartedMs")
    if not turn.get("executionRunId") or type(started) is not int or started <= 0:
        return None
    timing = {
        "runId": turn["executionRunId"],
        "startedMs": started,
        "observedMs": observed_ms,
        "elapsedSeconds": max(0, observed_ms - started) // 1000,
    }
    deadline = turn.get("executionDeadlineMs")
    if type(deadline) is int and deadline > 0:
        timing.update(
            deadlineMs=deadline,
            remainingSeconds=(max(0, deadline - observed_ms) + 999) // 1000,
        )
    return timing
