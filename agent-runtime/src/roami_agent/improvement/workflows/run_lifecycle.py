"""Coordinate run snapshots, evaluation capture and research synchronization."""

import json

from roami_agent.improvement.domain.contracts import digest
from roami_agent.improvement.domain.run_configuration import STAGES, code
from roami_agent.improvement.evaluation.case_catalog import case_identity
from roami_agent.improvement.evaluation.trial_evidence import cycle_usage, trial_summary
from roami_agent.protocol.errors import DomainError


class RunLifecycle:
    def __init__(self, runs, projection):
        self.runs, self.projection = runs, projection
        self.ledger = runs.ledger

    def begin_request(self, request):
        payload = json.loads(request["payload_json"])
        if payload.get("diagnostic"):
            return
        owner, run_id = request["owner"], request["id"]
        config = self.runs.settings(owner)
        snapshot = {
            "pipeline": config,
            "preferences": payload["preferences"],
            "machine_id": request["machine_id"],
            "suite_hash": payload["suite"]["content_hash"],
            "case_ids": [],
            "formal_daily": True,
        }
        self.runs.attach_request(request, snapshot)
        self.runs.node(owner, run_id, "evaluate", "running")
        self.runs.set_state(owner, run_id, "running")

    def capture_request(self, request):
        owner, run_id = request["owner"], request["id"]
        row = self.runs.request(owner, run_id)
        if not row:
            return
        row = dict(row)
        payload = json.loads(row["payload_json"])
        value = self.runs.get(owner, run_id)
        if row["state"] == "interrupted":
            self.runs.node(owner, run_id, "evaluate", "blocked", "RSI_CANCELLED")
            for stage in STAGES[1:]:
                self.runs.node(owner, run_id, stage, "skipped", "RSI_CANCELLED")
            self.runs.observations(owner, run_id)
            self.runs.set_state(owner, run_id, "cancelled")
            return
        if payload.get("diagnostic") and value["state"] != "running":
            return
        if row["cycle_id"]:
            cycle = self.ledger.get(owner, row["cycle_id"])
            self.runs.attach_cycle(owner, run_id, row["cycle_id"])
            by_case = {}
            for trial in cycle["trials"]:
                case_id = trial["case_id"]
                root = (
                    self.ledger.path.parent
                    / "runs"
                    / cycle["id"]
                    / (digest(case_id)[:20] + "-" + trial["arm"])
                )
                outcome = trial_summary(
                    {
                        "id": case_id,
                        "category": trial.get("category", ""),
                        "split": trial.get("split"),
                        "layer": trial.get("layer"),
                    },
                    trial,
                    root,
                    blocked_by=trial.get("blocked_by"),
                )
                outcome["source_hash"] = trial["case_hash"]
                outcome["arm"] = trial["arm"]
                by_case.setdefault(case_id, {})[trial["arm"]] = outcome
            report = cycle["report"] or {}
            cause = report.get("usage_blocker") or {}
            for case_id, arms in by_case.items():
                selected = (
                    cause["arm"]
                    if cause.get("case_id") == case_id and cause.get("arm") in arms
                    else "candidate"
                    if "candidate" in arms
                    else next(iter(arms))
                )
                outcome = dict(arms[selected])
                if len(arms) > 1:
                    outcome["arm_results"] = arms
                self.runs.case(owner, run_id, outcome)
            self.runs.observations(owner, run_id)
            self.runs.artifact(owner, run_id, "evaluate", "evaluation-report.json", report)
            self.runs.node(
                owner,
                run_id,
                "evaluate",
                "succeeded" if report.get("full_suite_complete") else "blocked",
                cause.get("code") or row["error_code"],
            )
            summary = {
                "cases": len(by_case),
                "expected_cases": cycle["manifest"].get("expected_cases"),
                "formal": cycle["manifest"].get("formal_daily_suite"),
                "evaluation_complete": report.get("evaluation_complete", False),
                "usage_blocker": report.get("usage_blocker"),
                **cycle_usage(cycle["trials"]),
            }
            from roami_agent.improvement.workflows.pipeline_reports import store_evaluation_summary

            store_evaluation_summary(self.runs, owner, run_id, summary=summary)
            if report.get("evaluation_complete") and self.runs.research_enabled(owner):
                self.runs.set_state(owner, run_id, "awaiting_research", summary)
                return
            self.runs.queue_report(owner, run_id, summary, reserve=True)
        else:
            error = code(row["error_code"])
            self.runs.case(
                owner,
                run_id,
                {
                    "case_id": "environment",
                    "category": "INFRA",
                    "kind": "environment",
                    "source_hash": digest("rsi-environment-v1"),
                    "state": "blocked",
                    "passed": False,
                    "pending": False,
                    "hard_passed": False,
                    "quality": None,
                    "signals": [error],
                    "checks": {},
                    "metrics": {"tokens": None},
                    "tools": [],
                    "roles": {},
                    "files": [],
                    "tool_calls": 0,
                },
            )
            self.runs.observations(owner, run_id)
            self.runs.node(owner, run_id, "evaluate", "blocked", error)
            from roami_agent.improvement.workflows.pipeline_reports import store_evaluation_summary

            store_evaluation_summary(self.runs, owner, run_id, summary={"error": error})
            self.runs.queue_report(
                owner,
                run_id,
                {
                    "cases": 0,
                    "expected_cases": len(value["snapshot"].get("case_ids", [])) or 60,
                    "error": error,
                },
                reserve=not bool(payload.get("diagnostic")),
            )

    def sync_research(self, owner):
        documents, receipts = self.projection.refresh(owner)
        for run_id, document in documents:
            try:
                self.runs.artifact(
                    owner,
                    run_id,
                    "review",
                    "formal-review-" + digest(document)[:8] + ".md",
                    document,
                )
            except DomainError:
                pass
        for run_id, stage, receipt in receipts:
            self.runs.artifact(
                owner, run_id, stage, "action-" + digest(receipt)[:20] + ".json", receipt
            )

    def freeze_cases(self, owner, run_id, suite):
        identities = {case["id"]: case_identity(case) for case in suite["cases"]}
        self.runs.freeze_case_definitions(owner, run_id, suite, identities)
