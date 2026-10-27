"""Issue repair receipts come from host verification, never executor completion claims."""

import json

from roami_agent.improvement.contracts import digest


def case_signals(ledger, owner, formal, case_id):
    from roami_agent.improvement.run_records import trial_summary

    with ledger.connection() as db:
        issues = db.execute(
            "SELECT id,code FROM rsi_pipeline_issues WHERE owner=? AND case_id=?", (owner, case_id)
        ).fetchall()
    if not issues:
        return []
    arms = {trial["arm"]: trial for trial in formal["trials"] if trial["case_id"] == case_id}
    if set(arms) != {"baseline", "candidate"}:
        return []
    candidate = arms["candidate"]
    if (
        not candidate["grade"].get("passed")
        or candidate["grade"].get("pending")
        or candidate.get("log_review", {}).get("complete") is not True
        or type(candidate.get("metrics", {}).get("tokens")) is not int
    ):
        return []
    observed = {}
    try:
        for arm, trial in arms.items():
            root = ledger.path.parent / "runs" / formal["id"] / (digest(case_id)[:20] + "-" + arm)
            if (
                not any(
                    (root / name).is_file()
                    for name in ("state/execution-log.json", "execution-log.json")
                )
                and trial.get("layer") != "mechanism"
            ):
                return []
            observed[arm] = trial_summary(
                {"id": case_id, "split": trial.get("split"), "layer": trial.get("layer")},
                trial,
                root,
            )["signals"]
    except (OSError, ValueError, KeyError):
        return []
    matched = []
    with ledger.connection() as db:
        for issue in issues:
            original = db.execute(
                "SELECT c.source_hash FROM rsi_pipeline_observations o JOIN rsi_pipeline_cases c ON c.run_id=o.run_id AND c.case_id=? JOIN rsi_pipeline_runs r ON r.id=o.run_id WHERE o.issue_id=? AND r.owner=? AND o.status='present' ORDER BY r.created_ms,r.id LIMIT 1",
                (case_id, issue["id"], owner),
            ).fetchone()
            if (
                original
                and original[0] == candidate["case_hash"]
                and issue["code"] in observed["baseline"]
                and issue["code"] not in observed["candidate"]
            ):
                matched.append(issue["id"])
    return (
        [
            {
                "case_id": case_id,
                "case_hash": candidate["case_hash"],
                "baseline_signals": observed["baseline"],
                "candidate_signals": observed["candidate"],
                "issue_ids": matched,
            }
        ]
        if matched
        else []
    )


def for_run(records, owner, run):
    context = run["snapshot"].get("comparison_context", {})
    if set(context) != {"source_hash", "model_hash", "environment_hash", "judge_hash"}:
        return [], [], {}
    case_rows = {case["case_id"]: case for case in run["cases"]}
    candidates = {
        issue["id"]: issue for issue in run["issues"] if issue["status"] == "not_reproduced"
    }
    cutoff = run["snapshot"].get("context_frozen_ms", run["created_ms"])
    verified, closed, evidence = [], [], {}
    with records.ledger.connection() as db:
        rows = db.execute(
            "SELECT improvement_id,created_ms,json_extract(data_json,'$.verification_context') AS context_json,json_extract(data_json,'$.verified_case_signals') AS signals_json,json_extract(data_json,'$.verification_cycles') AS cycles_json FROM rsi_improvement_events WHERE owner=? AND event='verify.completed' AND created_ms<=? AND json_extract(data_json,'$.verified_by')='host_code_verifier_v1' AND json_extract(data_json,'$.verification_context.source_hash')=? ORDER BY seq DESC",
            (owner, cutoff, context["source_hash"]),
        ).fetchall()
        for row in rows:
            if not row["context_json"] or not row["signals_json"] or not row["cycles_json"]:
                continue
            proof_context = json.loads(row["context_json"])
            if proof_context != context:
                continue
            cycles = json.loads(row["cycles_json"])
            signals = json.loads(row["signals_json"])
            if (
                not isinstance(cycles, list)
                or len(cycles) < 2
                or not all(isinstance(cycle, str) for cycle in cycles)
                or len(set(cycles)) != len(cycles)
                or not isinstance(signals, list)
            ):
                continue
            for signal in signals:
                if (
                    not isinstance(signal, dict)
                    or not all(
                        isinstance(signal.get(key), list)
                        and all(isinstance(value, str) for value in signal[key])
                        for key in ("baseline_signals", "candidate_signals", "issue_ids")
                    )
                    or not all(isinstance(signal.get(key), str) for key in ("case_id", "case_hash"))
                ):
                    continue
                case_id = signal["case_id"]
                case = case_rows.get(case_id)
                if (
                    not case
                    or case["source_hash"] != signal["case_hash"]
                    or case.get("passed") is not True
                    or case.get("pending")
                    or type(case.get("metrics", {}).get("tokens")) is not int
                ):
                    continue
                for issue_id in signal["issue_ids"]:
                    issue = candidates.get(issue_id)
                    if (
                        issue_id in evidence
                        or not issue
                        or issue["case_id"] != case_id
                        or issue["code"] not in signal["baseline_signals"]
                        or issue["code"] in signal["candidate_signals"]
                    ):
                        continue
                    later_failure = db.execute(
                        "SELECT 1 FROM rsi_pipeline_observations o JOIN rsi_pipeline_runs r ON r.id=o.run_id JOIN rsi_pipeline_cases c ON c.run_id=r.id AND c.case_id=? WHERE r.owner=? AND o.issue_id=? AND o.status='present' AND c.source_hash=? AND r.created_ms>? AND (r.created_ms<? OR (r.created_ms=? AND r.id<=?)) LIMIT 1",
                        (
                            case_id,
                            owner,
                            issue_id,
                            signal["case_hash"],
                            row["created_ms"],
                            run["created_ms"],
                            run["created_ms"],
                            run["id"],
                        ),
                    ).fetchone()
                    if later_failure:
                        continue
                    verified.append(issue_id)
                    evidence[issue_id] = {
                        "verified_by": "host_code_verifier_v1",
                        "verified_ms": row["created_ms"],
                        "verification_cycles": cycles,
                        "case_id": case_id,
                        "case_hash": signal["case_hash"],
                        **context,
                    }
                    closure = db.execute(
                        "SELECT event,data_json FROM rsi_improvement_events WHERE owner=? AND improvement_id=? AND event IN ('observation.closed_fixed','observation.reopened') AND (created_ms<=? OR json_extract(data_json,'$.cycle_id')=?) ORDER BY seq DESC LIMIT 1",
                        (owner, row["improvement_id"], run["created_ms"], run.get("cycle_id")),
                    ).fetchone()
                    if closure and closure["event"] == "observation.closed_fixed":
                        cycle_id = json.loads(closure["data_json"]).get("cycle_id")
                        cycle = db.execute(
                            "SELECT manifest_json FROM rsi_cycles WHERE id=? AND owner=? AND state='completed'",
                            (cycle_id, owner),
                        ).fetchone()
                        if cycle:
                            manifest = json.loads(cycle[0])
                            if (
                                manifest.get("source_builds", {}).get("candidate")
                                == context["source_hash"]
                                and manifest.get("model_hash") == context["model_hash"]
                                and manifest.get("judge_hash") == context["judge_hash"]
                                and manifest.get("machine", {}).get("environment_hash")
                                == context["environment_hash"]
                            ):
                                closed.append(issue_id)
    return verified, closed, evidence
