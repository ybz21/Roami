"""Owner-scoped, as-of-run result views; unknowns never become repair receipts."""

import json

from roami_agent.improvement.case_catalog import case_definitions
from roami_agent.improvement.run_records import STAGES
from roami_agent.protocol.errors import DomainError


def _priority(code):
    if code in {"RSI_UNEXPECTED_MODEL_TOOL", "RSI_PRIVATE_OUTPUT_REQUIRED"}:
        return "P0", "boundary_violation"
    if code in {"RSI_NATIVE_TASK_FAILED", "MODEL_OUTPUT_LENGTH", "RSI_NATIVE_TASK_REQUIRED"}:
        return "P1", "delivery_blocked"
    return "P2", "review_required"


def _run(records, owner, row, sequence, selected_id):
    value = records.get(owner, row["id"])
    snapshot = value["snapshot"]
    definitions = snapshot.get("case_definitions", {})
    case_rows = {case["case_id"]: case for case in value["cases"]}
    ids = snapshot.get("case_ids") or list(case_rows)
    categories, results = [], {}
    for ident in ids:
        case = case_rows.get(ident, {})
        definition = definitions.get(ident, {})
        categories.append(
            {
                "id": ident,
                "name": definition.get("name") or case.get("name") or ident,
                "description": (definition.get("description") or case.get("description") or "")
                if row["id"] == selected_id
                else "",
                "group": "mechanism"
                if case.get("kind") == "mechanism" or definition.get("layer") == "mechanism"
                else "public"
                if str(definition.get("layer", "")).startswith("public")
                else "authored",
            }
        )
        results[ident] = (
            "unknown"
            if case.get("passed") is True and case.get("metrics", {}).get("tokens") is None
            else "passed"
            if case.get("passed") is True and not case.get("pending")
            else "pending"
            if case.get("pending")
            else "running"
            if case.get("state") == "running"
            else case["state"]
            if case.get("state") in {"blocked", "unknown", "cancelled"}
            else "failed"
            if case
            else "not_run"
        )
    latest = {}
    for node in value["nodes"]:
        if node["node"] not in latest or node["attempt"] > latest[node["node"]]["attempt"]:
            latest[node["node"]] = node
    workflow = {
        stage: {
            "state": latest.get(stage, {}).get("state", "pending"),
            "error": latest.get(stage, {}).get("error_code"),
            "artifacts": [
                {"id": artifact["id"], "name": artifact["name"]}
                for artifact in value["artifacts"]
                if artifact["node"] == stage
            ],
        }
        for stage in STAGES
    }
    triage = {}
    report = next(
        (artifact for artifact in value["artifacts"] if artifact["name"] == "review.md"), None
    )
    for artifact in value["artifacts"]:
        if artifact["name"] not in {"issue-plan.json", "issue-analysis.json"}:
            continue
        try:
            plan = json.loads(records.read_artifact(owner, value["id"], artifact["id"])["text"])
            if not isinstance(plan, dict):
                continue
            for ident, decision in plan.items():
                entry = {"priority": decision} if isinstance(decision, str) else decision
                if not isinstance(entry, dict) or entry.get("priority") not in {
                    "P0",
                    "P1",
                    "P2",
                    "P3",
                }:
                    continue
                entry = {
                    "priority": entry["priority"],
                    **(
                        {"reason": entry["reason"]}
                        if isinstance(entry.get("reason"), str) and len(entry["reason"]) <= 2000
                        else {}
                    ),
                }
                previous = triage.get(ident, {})
                triage[ident] = {
                    **previous,
                    **entry,
                    "artifact": {
                        "id": report["id"] if report else artifact["id"],
                        "name": report["name"] if report else artifact["name"],
                        "runId": value["id"],
                    },
                }
        except (DomainError, ValueError):
            continue
    context = snapshot.get("comparison_context", {})
    from roami_agent.improvement.issue_verification import for_run

    verified, closed, verification_evidence = for_run(records, owner, value)
    blockers = {
        "MODEL_PROXY_DAILY_LIMIT",
        "MODEL_PROXY_USAGE_UNKNOWN",
        "MODEL_PROXY_CURRENCY_MISMATCH",
    }
    blocker = next(
        (node.get("error_code") for node in value["nodes"] if node.get("error_code") in blockers),
        None,
    )
    if blocker is None:
        blocker = next(
            (
                signal
                for case in value["cases"]
                for signal in case.get("signals", [])
                if signal in blockers
            ),
            None,
        )
    missing = "unknown:" + value["id"]
    return {
        "id": value["id"],
        "rawState": value["state"],
        "blocker": blocker,
        "publication": value.get("issue"),
        "sequence": sequence,
        "time": value["created_ms"],
        "mode": "full" if snapshot.get("formal_daily") else "quick",
        "state": "running"
        if value["state"] in {"running", "queued", "reviewing", "report_queued"}
        else "interrupted"
        if value["state"] in {"cancelled", "interrupted"}
        else "partial"
        if not ids
        or any(
            results.get(ident)
            in {"pending", "not_run", "running", "blocked", "unknown", "cancelled"}
            for ident in ids
        )
        else "completed",
        "scope": ids,
        "results": results,
        "verified": verified,
        "verifiedSourcePairs": verified,
        "closed": closed,
        "verificationEvidence": verification_evidence if row["id"] == selected_id else {},
        "source": context.get("source_hash") or snapshot.get("source_hash") or missing,
        "suite": snapshot.get("suite_hash") or missing,
        "judge": context.get("judge_hash") or missing,
        "models": context.get("model_hash") or missing,
        "machine": context.get("environment_hash") or snapshot.get("machine_id") or missing,
        "caseDefinitions": categories,
        "caseEvidence": case_rows if row["id"] == selected_id else {},
        "caseHashes": snapshot.get("source_case_hashes")
        or {ident: case["source_hash"] for ident, case in case_rows.items()},
        "workflow": workflow,
        "triage": triage,
        "issueObservations": {issue["id"]: issue["status"] for issue in value["issues"]},
    }


def results_view(records, owner, run_id):
    current = records.get(owner, run_id)
    with records.ledger.connection() as db:
        rows = db.execute(
            "SELECT id,created_ms,ROW_NUMBER() OVER (ORDER BY created_ms,id) AS sequence FROM rsi_pipeline_runs WHERE owner=? AND (created_ms<? OR (created_ms=? AND id<=?)) ORDER BY created_ms DESC,id DESC LIMIT 101",
            (owner, current["created_ms"], current["created_ms"], run_id),
        ).fetchall()
        complete = len(rows) <= 100
        rows = list(reversed(rows[:100]))
        issue_rows = db.execute(
            "SELECT DISTINCT i.* FROM rsi_pipeline_issues i JOIN rsi_pipeline_observations o ON o.issue_id=i.id JOIN rsi_pipeline_runs r ON r.id=o.run_id WHERE i.owner=? AND r.owner=? AND (r.created_ms<? OR (r.created_ms=? AND r.id<=?)) ORDER BY i.created_ms,i.id",
            (owner, owner, current["created_ms"], current["created_ms"], run_id),
        ).fetchall()
        observations = [
            dict(row)
            for row in db.execute(
                "SELECT o.* FROM rsi_pipeline_observations o JOIN rsi_pipeline_runs r ON r.id=o.run_id WHERE r.owner=? AND (r.created_ms<? OR (r.created_ms=? AND r.id<=?)) ORDER BY r.created_ms,r.id",
                (owner, current["created_ms"], current["created_ms"], run_id),
            )
        ]
    runs = [_run(records, owner, row, row["sequence"], run_id) for row in rows]
    known_ids = {row["id"] for row in rows}
    definitions = []
    for row in issue_rows:
        history = [
            value
            for value in observations
            if value["issue_id"] == row["id"] and value["run_id"] in known_ids
        ]
        first = next((value["run_id"] for value in history if value["status"] == "present"), None)
        original = next(
            (
                value["run_id"]
                for value in observations
                if value["issue_id"] == row["id"] and value["status"] == "present"
            ),
            None,
        )
        if first is None:
            if not history or original is None:
                continue
            first = history[0]["run_id"]
        priority, reason = _priority(row["code"])
        decision = next(
            (run["triage"][row["id"]] for run in reversed(runs) if row["id"] in run["triage"]), None
        )
        if decision:
            priority = decision["priority"]
            reason = "codex_plan"
        definitions.append(
            {
                "id": row["id"],
                "name": row["code"],
                "signal": row["code"],
                "type": "fix",
                "priority": priority,
                "firstRun": first,
                "originalRun": original,
                "historyTruncated": original not in known_ids,
                "cases": [row["case_id"]],
                "fingerprint": row["case_id"] + ":" + row["code"],
                "reason": "livePriority." + reason,
                "acceptance": "liveAcceptance",
                "reasonText": decision.get("reason") if decision else None,
                "analysisArtifact": decision["artifact"] if decision else None,
            }
        )
    cases = {case["id"]: case for run in runs for case in run["caseDefinitions"]}
    return {
        "runs": runs,
        "issues": definitions,
        "cases": list(cases.values()),
        "history_complete": complete,
    }


def catalog_view():
    return [
        {
            "id": value["id"],
            "name": value["name"],
            "description": value["description"],
            "kind": value["kind"],
            "source_case_id": value.get("source_case_id"),
        }
        for value in case_definitions()
    ]
