"""Per-attempt wall-clock facts; absent deadlines never become runtime limits."""


def execution_timing(turn, observed_ms, *, enclosing_deadline_ms=None):
    started = turn.get("executionStartedMs")
    native = bool(turn.get("executionRunId")) and type(started) is int and started > 0
    enclosing = type(enclosing_deadline_ms) is int and enclosing_deadline_ms > 0
    if not native and not enclosing:
        return None
    timing = {"observedMs": observed_ms}
    if native:
        timing.update(
            runId=turn["executionRunId"],
            startedMs=started,
            elapsedSeconds=max(0, observed_ms - started) // 1000,
        )
    own_deadline = turn.get("executionDeadlineMs") if native else None
    deadlines = [d for d in (own_deadline, enclosing_deadline_ms) if type(d) is int and d > 0]
    if deadlines:
        deadline = min(deadlines)
        timing.update(
            deadlineMs=deadline,
            remainingSeconds=(max(0, deadline - observed_ms) + 999) // 1000,
        )
        if enclosing and deadline == enclosing_deadline_ms:
            timing["deadlineSource"] = "enclosing_execution"
    return timing
