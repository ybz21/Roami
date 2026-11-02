"""Load prior host receipts and their matching observation closures."""

import json


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
