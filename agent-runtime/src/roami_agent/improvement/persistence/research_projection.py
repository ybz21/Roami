"""Atomically materialize research action states into the run read model."""

import json


class ResearchProjection:
    def __init__(self, ledger):
        self.ledger = ledger

    def refresh(self, owner):
        documents = []
        receipts = []
        with self.ledger.connection() as db:
            runs = db.execute(
                "SELECT id,cycle_id,state FROM rsi_pipeline_runs WHERE owner=? AND mode!='diagnostic' AND cycle_id IS NOT NULL",
                (owner,),
            ).fetchall()
            reports = db.execute(
                "SELECT * FROM rsi_review_reports WHERE owner=?", (owner,)
            ).fetchall()
            actions = [
                dict(r) for r in db.execute("SELECT * FROM rsi_actions WHERE owner=?", (owner,))
            ]
            for run in runs:
                matched = [
                    r
                    for r in reports
                    if run["cycle_id"]
                    in json.loads(r["report_json"]).get("source_cycles", [r["cycle_id"]])
                ]
                related = {r["cycle_id"] for r in matched} | {run["cycle_id"]}
                items = {
                    r[0]
                    for r in db.execute(
                        "SELECT improvement_id FROM rsi_report_items WHERE owner=? AND cycle_id IN ("
                        + ",".join("?" for _ in related)
                        + ")",
                        (owner, *related),
                    )
                }
                for kind, stage in (
                    ("review", "review"),
                    ("issue", "issue"),
                    ("repair", "repair"),
                    ("verify", "verify"),
                    ("publish", "publish"),
                    ("activate", "observe"),
                ):
                    found = [
                        a
                        for a in actions
                        if a["kind"] == kind
                        and (
                            a["subject"] in related
                            or a["subject"].split(":")[0] in items
                            or json.loads(a["payload_json"]).get("improvement_id") in items
                        )
                    ]
                    if found:
                        states = {a["state"] for a in found}
                        state = (
                            "blocked"
                            if states & {"blocked", "waiting_budget"}
                            else "failed"
                            if states & {"failed"}
                            else "unknown"
                            if states & {"unknown"}
                            else "running"
                            if states & {"running", "queued"}
                            else "succeeded"
                            if states <= {"done", "completed"}
                            else "pending"
                        )
                        db.execute(
                            "UPDATE rsi_pipeline_nodes SET state=? WHERE run_id=? AND node=?",
                            (state, run["id"], stage),
                        )
                        for action in found:
                            result = json.loads(action["result_json"] or "{}")
                            receipt = {
                                "action_id": action["id"],
                                "kind": kind,
                                "state": action["state"],
                                "error_code": action["error_code"],
                                "created_ms": action["created_ms"],
                                "result": {
                                    key: result[key]
                                    for key in (
                                        "verified_by",
                                        "verification_cycles",
                                        "verification_context",
                                        "regression_output_hash",
                                        "base_build_hash",
                                        "candidate_build_hash",
                                    )
                                    if key in result
                                },
                            }
                            receipts.append((run["id"], stage, receipt))
                for report in matched:
                    data = json.loads(report["report_json"])
                    if report["issue_json"]:
                        db.execute(
                            "UPDATE rsi_pipeline_runs SET issue_json=? WHERE id=?",
                            (report["issue_json"], run["id"]),
                        )
                    documents.append((run["id"], data["document"]))
                if items:
                    states = {
                        r[0]
                        for r in db.execute(
                            "SELECT state FROM rsi_improvements WHERE owner=? AND id IN ("
                            + ",".join("?" for _ in items)
                            + ")",
                            (owner, *items),
                        )
                    }
                    observation = (
                        "succeeded"
                        if states and states <= {"closed", "closed_fixed", "rejected"}
                        else "running"
                        if "observing" in states
                        else "pending"
                    )
                    db.execute(
                        "UPDATE rsi_pipeline_nodes SET state=? WHERE run_id=? AND node='observe'",
                        (observation, run["id"]),
                    )
                    if states and states <= {"closed", "closed_fixed", "rejected"}:
                        db.execute(
                            "UPDATE rsi_pipeline_runs SET state='completed' WHERE id=?",
                            (run["id"],),
                        )
        return documents, receipts
