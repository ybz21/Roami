"""Read execution files into a frozen trial summary without database access."""

import json
from pathlib import Path

from roami_agent.improvement.domain.admission_blocking import blocking_code
from roami_agent.improvement.domain.contracts import digest
from roami_agent.improvement.domain.run_configuration import code
from roami_agent.improvement.evaluation.case_catalog import case_identity


def cycle_usage(trials):
    metrics = [trial.get("metrics", {}) for trial in trials]

    def total(name, default=None):
        values = [item.get(name, default) for item in metrics]
        return sum(values) if values and all(type(v) is int and v >= 0 for v in values) else None

    tokens, review = total("tokens"), total("artifact_review_tokens", 0)
    observed = [
        item["tokens"]
        if type(item.get("tokens")) is int and item["tokens"] >= 0
        else item.get("observed_tokens")
        for item in metrics
    ]
    return {
        "evaluation_tokens": tokens,
        "known_evaluation_tokens": sum(v for v in observed if type(v) is int and v >= 0),
        "generation_tokens": tokens - review
        if tokens is not None and review is not None and tokens >= review
        else None,
        "artifact_review_tokens": review,
    }


def trial_summary(case, result, root=None, *, blocked_by=None):
    grade, metrics = result.get("grade", {}), result.get("metrics", {})
    signals = (
        {code(result.get("execution_error") or grade.get("reason"))}
        if not grade.get("passed")
        else set()
    )
    signals -= {"UNKNOWN", "assertions_passed"}
    if cause := blocking_code(result):
        signals.add(cause)
    checks = {code(k): v for k, v in grade.get("checks", {}).items() if type(v) is bool}
    signals.update("check:" + k for k, v in checks.items() if not v)
    tools, roles, files = [], {}, []
    execution_log_found = False
    if root:
        root = Path(root)
        for name in ("state/execution-log.json", "execution-log.json"):
            path = root / name
            if not path.is_file():
                continue
            data = json.loads(path.read_text())
            execution_log_found = True
            for item in data.get("tool_calls", []):
                error = None
                if item.get("state") == "failed":
                    try:
                        output = item.get("result_json", {})
                        output = json.loads(output) if isinstance(output, str) else output
                        output = json.loads(output.get("text", "{}"))
                        error = code(output.get("error"))
                    except (TypeError, ValueError):
                        error = "TOOL_FAILED"
                    signals.add(error)
                tools.append(
                    {
                        "name": code(item.get("tool_name")),
                        "state": item.get("state"),
                        "error": error,
                    }
                )
            break
        model = root / "model-log.json"
        if model.is_file():
            model_log = json.loads(model.read_text())
            for error in model_log.get("gateway_errors", []):
                if type(error.get("count")) is int and error["count"] > 0:
                    signals.add(code(error.get("code")))
            for item in model_log.get("requests", []):
                role = code(item.get("role"))
                usage = item.get("measurement") or {}
                row = roles.setdefault(
                    role, {"calls": 0, "known_input": 0, "known_output": 0, "unknown": 0}
                )
                row["calls"] += 1
                if type(usage.get("inputTokens")) is int and type(usage.get("outputTokens")) is int:
                    row["known_input"] += usage["inputTokens"]
                    row["known_output"] += usage["outputTokens"]
                else:
                    row["unknown"] += 1
                if item.get("error_code"):
                    signals.add(code(item["error_code"]))
        files = [
            str(p.relative_to(root / "workspace"))
            for p in (root / "workspace").rglob("*")
            if p.is_file()
            and p.suffix in {".py", ".md", ".html", ".json", ".csv", ".svg", ".pptx"}
            and "__pycache__" not in p.parts
        ][:32]
    blocked = bool(
        signals
        & {
            "RSI_TOKEN_BUDGET",
            "RSI_DAILY_BUDGET",
            "RSI_REQUEST_BUDGET",
            "UPSTREAM_USAGE_UNKNOWN",
            "RSI_USAGE_UNKNOWN",
            "MODEL_HTTP_402",
            "MODEL_PROXY_DAILY_LIMIT",
            "MODEL_PROXY_USAGE_UNKNOWN",
            "MODEL_PROXY_CURRENCY_MISMATCH",
        }
    )
    state = (
        "blocked"
        if blocked
        else "pending_score"
        if grade.get("pending")
        else "passed"
        if grade.get("passed")
        else "failed"
    )
    identity = case_identity(case)
    return {
        "case_id": case["id"],
        **({"blocked_by": blocked_by} if blocked_by else {}),
        "name": identity["name"],
        "description": identity["description"],
        "category": case.get("category", ""),
        "kind": "mechanism"
        if case.get("layer") == "mechanism" or case.get("judge", {}).get("kind") == "mechanism"
        else "task",
        "source_hash": digest(case),
        "state": state,
        "passed": grade.get("passed") is True,
        "hard_passed": grade.get("hard_passed") is True,
        "pending": grade.get("pending") is True,
        "quality": grade.get("quality"),
        "checks": checks,
        "signals": sorted(signals),
        "metrics": {
            k: metrics.get(k)
            for k in ("tokens", "token_coverage", "model_calls", "elapsed_ms", "model_ms")
        },
        "tools": tools,
        "tool_calls": len(tools) if execution_log_found else metrics.get("tool_calls"),
        "roles": roles,
        "files": files,
    }
