"""Measure every attempted tool call, including failures followed by recovery."""

import json
from collections import Counter

from roami_agent.improvement.integrations.artifact_paths import relative_file
from roami_agent.protocol.errors import DomainError


def logged_tool_process(root):
    for name in (
        "interrupted-execution-log.json",
        "state/execution-log.json",
        "execution-log.json",
    ):
        try:
            path = relative_file(root, name)
            if not path.exists():
                continue
            if not path.is_file() or path.stat().st_size > 64_000_000:
                break
            value = json.loads(path.read_text())
            if (
                isinstance(value, dict)
                and isinstance(value.get("tool_calls"), list)
                and all(isinstance(record, dict) for record in value["tool_calls"])
            ):
                return tool_process_metrics(
                    value["tool_calls"], complete=value.get("complete", True) is True
                )
            break
        except (DomainError, OSError, ValueError):
            break
    return {"tool_process_coverage": "missing"}


def tool_result(record):
    try:
        value = record.get("result_json") or {}
        value = json.loads(value) if isinstance(value, str) else value
        if isinstance(value, dict) and "text" in value:
            value = json.loads(value["text"])
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def tool_process_metrics(records, *, complete=True):
    failures, unknown, rejected, arguments, successes = 0, 0, 0, 0, 0
    codes, first = Counter(), {}
    for record in records:
        value, state = tool_result(record), record.get("state")
        indeterminate = state not in {"succeeded", "failed"} or value.get("outcomeKnown") is False
        failed = not indeterminate and (
            state == "failed"
            or bool(value.get("error"))
            or (type(value.get("exitCode")) is int and value["exitCode"] != 0)
        )
        succeeded = state == "succeeded" and not failed and not indeterminate
        successes += succeeded
        failures += failed
        unknown += indeterminate
        if not succeeded:
            error = value.get("error") or (
                "COMMAND_NONZERO_EXIT"
                if value.get("exitCode")
                else "TOOL_OUTCOME_UNKNOWN"
                if indeterminate
                else "TOOL_FAILED"
            )
            codes[str(error)] += 1
            arguments += error in {"INVALID_TOOL_ARGUMENTS", "INVALID_CLI_ARGUMENTS"}
            rejected += value.get("executionStarted") is False
        first.setdefault(record.get("turn_id"), succeeded)
    count, errors = len(records), len(records) - successes
    measured = complete and not unknown
    return {
        "tool_process_coverage": "complete" if measured else "partial",
        "tool_calls": count,
        "tool_failures": failures,
        "tool_unknowns": unknown,
        "tool_errors": errors,
        "tool_argument_failures": arguments,
        "tool_admission_failures": rejected,
        "tool_failure_codes": dict(codes),
        "tool_failure_rate": failures / count if measured and count else None,
        "tool_error_rate": errors / count if measured and count else None,
        "tool_process_score": 100 * successes / count if measured and count else None,
        "tool_first_calls": len(first),
        "tool_first_successes": sum(first.values()),
        "tool_first_attempt_success_rate": sum(first.values()) / len(first)
        if measured and first
        else None,
    }
