"""Inspect every trial's metrics and concrete logs without another model request."""

import hashlib
import json
import statistics
from collections import Counter

from roami_agent.improvement.contracts import digest, evaluation_arms, relative_file
from roami_agent.protocol.errors import DomainError

LOGS = {
    "native_files": ("model-log.json", "execution-log.json"),
    "protocol_fixture": ("model-log.json", "execution-log.json"),
    "isolated_native_worker": ("model-log.json", "state/execution-log.json"),
    "runtime_regression_variant": ("regression.log",),
    "external_worker": ("execution-log.json",),
}
ACTIONS = {
    "failed_assertion": "复现失败断言，核对实际产物和执行链，再修改执行逻辑；不得放宽评分标准。",
    "judge_pending": "补齐独立产物评分；不能把文件存在视为质量通过。",
    "usage_unknown": "核对各角色、重试和异步维护的用量；计量完整前不宣称节省Token。",
    "request_retries": "回看请求错误及退避记录，区分服务故障与可修复参数错误。",
    "tool_failed": "检查具体工具的参数、错误和恢复步骤，修复原因后回归验证。",
    "unknown_tool_outcome": "先只读对账实际状态；写入结果未知时不要直接重试。",
    "repeated_read": "核对输入及结果版本；仅在证据仍有效时复用，保留必要的最终验证。",
    "log_unavailable": "修复日志采集或读取问题后再回顾；当前回顾不完整。",
    "quality_regression": "定位候选退步的断言与对应调用链，修复后重跑，不用速度收益抵消质量下降。",
    "time_regression": "比较成功交付的模型和工具关键耗时，提出可复现的单项改动。",
    "token_regression": "比较所有角色的输入、输出与重试日志，定位多余上下文或重复轮次。",
}


def review_trial(trial, root):
    findings, evidence, tools, slow_spans, requests = [], [], [], [], []
    complete = True

    def finding(code, refs, **detail):
        findings.append(
            {"code": code, "evidence": refs, "detail": detail, "suggestion": ACTIONS[code]}
        )

    names = list(LOGS.get(trial.get("execution_kind"), ("execution-log.json",)))
    if trial.get("isolation", {}).get("project_runtime"):
        names.append("project-runtime-log.json")
    names.extend(
        name for name in ("worker-stdout.log", "worker-stderr.log") if (root / name).exists()
    )
    for name in names:
        try:
            path = relative_file(root, name)
            if not path.is_file() or path.stat().st_size > 64_000_000:
                raise ValueError("missing_or_oversized")
            raw = path.read_bytes()
            reference = {"file": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
            if name.endswith(".json"):
                value = json.loads(raw)
                if name.endswith("model-log.json"):
                    records = value["requests"]
                    if not isinstance(records, list) or any(
                        not isinstance(r, dict) for r in records
                    ):
                        raise ValueError("invalid_requests")
                    for index, record in enumerate(records):
                        if not isinstance(record["role"], str) or not isinstance(
                            record["measurement"], dict
                        ):
                            raise TypeError("invalid_measurement")
                        payload = json.dumps(
                            [record["messages"], record["tools"]], ensure_ascii=False
                        ).encode()
                        events = record["events"]
                        requests.append(
                            {
                                "role": record["role"],
                                "measurement": record["measurement"],
                                "request_bytes": len(payload),
                                "request_hash": hashlib.sha256(payload).hexdigest(),
                                "event_counts": dict(Counter(e["kind"] for e in events)),
                                "evidence": {**reference, "record": index},
                            }
                        )
                else:
                    records, traces = value["tool_calls"], value["traces"]
                    if not isinstance(records, list) or not isinstance(traces, list):
                        raise ValueError("invalid_execution_log")
                    if any(
                        not isinstance(t, dict)
                        or any(
                            not isinstance(t.get(key), str)
                            for key in ("id", "state", "tool_name", "arguments_json")
                        )
                        for t in records
                    ):
                        raise ValueError("invalid_tool_log")
                    for index, tool in enumerate(records):
                        tools.append({**tool, "evidence": {**reference, "record": index}})
                    for trace in traces:
                        for span in trace["spans"]:
                            if span.get("durationMs") is not None:
                                slow_spans.append(
                                    {
                                        "name": span["name"],
                                        "duration_ms": span["durationMs"],
                                        "state": span["state"],
                                        "evidence": {**reference, "span_id": span["spanId"]},
                                    }
                                )
            else:
                text = raw.decode("utf-8")
                if name == "regression.log" and not text.strip():
                    raise ValueError("empty_regression_log")
                # Read every line; preserve its identity rather than forwarding private content.
                reference["lines_reviewed"] = len(text.splitlines())
            evidence.append(reference)
        except (OSError, ValueError, KeyError, TypeError, DomainError):
            complete = False
            finding("log_unavailable", [{"file": name}])

    grade, metrics = trial["grade"], trial["metrics"]
    if "model-log.json" in names and len(requests) != metrics.get("model_calls"):
        complete = False
        finding("log_unavailable", [{"file": "model-log.json"}], reason="request_count_mismatch")
    if not grade["passed"]:
        finding(
            "judge_pending" if grade.get("pending") else "failed_assertion",
            [{"record": "grade"}],
            reason=grade.get("reason"),
        )
    if metrics.get("tokens") is None:
        finding("usage_unknown", [{"record": "metrics"}], coverage=metrics.get("token_coverage"))
    if metrics.get("retries", 0):
        finding("request_retries", [{"record": "metrics.requests"}], count=metrics["retries"])
    previous = {}
    for tool in tools:
        state = tool["state"]
        if state in {"failed", "unknown"}:
            finding(
                "unknown_tool_outcome" if state == "unknown" else "tool_failed",
                [tool["evidence"]],
                tool=tool["tool_name"],
                tool_call_id=tool["id"],
            )
        if tool["tool_name"] in {"read", "file_read", "artifact_read"} and state == "succeeded":
            key = digest([tool["tool_name"], tool["arguments_json"], tool.get("result_json")])
            if key in previous:
                finding("repeated_read", [previous[key], tool["evidence"]], tool=tool["tool_name"])
            previous[key] = tool["evidence"]
    return {
        "complete": complete,
        "metrics_reviewed": True,
        "logs": evidence,
        "model_requests_reviewed": len(requests),
        "tool_records_reviewed": len(tools),
        "slowest_spans": sorted(slow_spans, key=lambda s: s["duration_ms"], reverse=True)[:5],
        "requests": requests,
        "findings": findings,
        "method": "deterministic_evidence_review_v1; suggestions are hypotheses, not proven causes",
    }


def review_cycle(manifest, trials):
    details, pair_findings = [], []
    expected = set(manifest["case_ids"])
    required_arms = evaluation_arms(manifest)
    executed = {arm: {t["case_id"] for t in trials.get(arm, [])} for arm in required_arms}
    full = all(ids == expected for ids in executed.values()) and not any(
        trials.get(arm) for arm in set(trials) - set(required_arms)
    )
    index = {arm: {t["case_id"]: t for t in items} for arm, items in trials.items()}
    for case_id in sorted(executed["baseline"] & executed.get("candidate", set())):
        a, b = index["baseline"][case_id], index["candidate"][case_id]
        codes = []
        if a["grade"]["passed"] and (
            not b["grade"]["passed"] or b["grade"]["quality"] < a["grade"]["quality"]
        ):
            codes.append("quality_regression")
        if a.get("verified_delivery") and b.get("verified_delivery"):
            for metric, code in (("elapsed_ms", "time_regression"), ("tokens", "token_regression")):
                left, right = a["metrics"].get(metric), b["metrics"].get(metric)
                if left is not None and left > 0 and right is not None and right > left * 1.05:
                    codes.append(code)
        pair_findings.extend(
            {
                "case_id": case_id,
                "code": code,
                "suggestion": ACTIONS[code],
                "evidence": ["baseline:" + case_id, "candidate:" + case_id],
            }
            for code in codes
        )
    aggregates, counts = {}, Counter()
    for arm, items in trials.items():
        known = len(items) == len(expected) and all(
            t["metrics"].get("tokens") is not None for t in items
        )
        tokens = sum(t["metrics"].get("tokens") or 0 for t in items)
        passed = sum(t["grade"]["passed"] for t in items)
        deliveries = sum(bool(t.get("verified_delivery")) for t in items)
        times = [
            t["metrics"]["elapsed_ms"]
            for t in items
            if t.get("verified_delivery") and t["metrics"].get("elapsed_ms") is not None
        ]

        def metric_sum(name, records=items):
            values = [t["metrics"].get(name) for t in records]
            return sum(values) if all(type(v) is int and v >= 0 for v in values) else None

        layers, roles = {}, {}
        for trial in items:
            layer = layers.setdefault(
                trial.get("layer", "unclassified"), {"trials": 0, "quality_sum": 0}
            )
            layer["trials"] += 1
            layer["quality_sum"] += trial["grade"]["quality"]
            for request in trial["log_review"]["requests"]:
                role = roles.setdefault(
                    request["role"], {"requests": 0, "input_tokens": 0, "output_tokens": 0}
                )
                role["requests"] += 1
                for source, target in (
                    ("inputTokens", "input_tokens"),
                    ("outputTokens", "output_tokens"),
                ):
                    value = request["measurement"].get(source)
                    role[target] = (
                        role[target] + value
                        if role[target] is not None and type(value) is int and value >= 0
                        else None
                    )
        aggregates[arm] = {
            "executed": len(items),
            "passed": passed,
            "total_tokens_including_failures": tokens if known else None,
            "observed_tokens": sum(
                t["metrics"].get("observed_tokens", t["metrics"].get("tokens")) or 0 for t in items
            ),
            "tokens_per_pass_including_failures": tokens / passed if known and passed else None,
            "tokens_per_verified_delivery_including_failures": tokens / deliveries
            if known and deliveries
            else None,
            "verified_delivery_time_p50_ms": statistics.median(times) if times else None,
            "tool_calls": metric_sum("tool_calls"),
            "model_calls": metric_sum("model_calls"),
            "quality_by_layer": {
                name: {
                    "trials": values["trials"],
                    "mean_quality": values["quality_sum"] / values["trials"],
                }
                for name, values in layers.items()
            },
            "model_roles": roles,
        }
        for trial in items:
            review = trial["log_review"]
            counts.update(f["code"] for f in review["findings"])
            details.append(
                {"arm": arm, "case_id": trial["case_id"], "split": trial["split"], **review}
            )
    counts.update(f["code"] for f in pair_findings)
    summary = {
        "complete": full and all(t["complete"] for t in details),
        "expected_trials": len(required_arms) * len(expected),
        "metrics_reviewed": len(details),
        "logs_reviewed": sum(t["complete"] for t in details),
        "finding_counts": dict(counts),
        "cost": aggregates,
        "review_model_tokens": 0,
    }
    return {
        "summary": summary,
        "coverage": {
            "expected_cases": len(expected),
            "executed_cases": {arm: len(ids) for arm, ids in executed.items()},
            "execution_complete": full,
        },
        "trials": details,
        "pair_findings": pair_findings,
        "optimizer_feedback": "Development evidence only; validation/holdout/private logs stay outside optimizer inputs.",
    }
