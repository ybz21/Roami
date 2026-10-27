"""ResearchReports persistence within the research aggregate."""

import json
import re

from roami_agent.improvement.domain.contracts import digest, require


class ResearchReports:
    def __init__(self, owner):
        self.owner, self.ledger = owner, owner.ledger

    def save_report(self, action, report):
        self.owner.record_findings(action, [p["finding"] for p in report["points"]])
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.owner._owned_action(db, action)
            prior = db.execute(
                "SELECT report_json FROM rsi_review_reports WHERE owner=? AND cycle_id=?",
                (action["owner"], report["cycle_id"]),
            ).fetchone()
            require(prior is None or json.loads(prior[0]) == report, "RSI_REVIEW_REPORT_CONFLICT")
            db.execute(
                "INSERT OR IGNORE INTO rsi_review_reports VALUES(?,?,?,NULL,?)",
                (action["owner"], report["cycle_id"], json.dumps(report), self.owner.clock()),
            )
            for point in report["points"]:
                db.execute(
                    "INSERT OR IGNORE INTO rsi_report_items VALUES(?,?,?,?)",
                    (
                        action["owner"],
                        report["cycle_id"],
                        digest([action["owner"], point["id"]]),
                        point["id"],
                    ),
                )

    def report(self, owner, cycle_id):
        with self.ledger.connection() as db:
            row = db.execute(
                "SELECT report_json,issue_json FROM rsi_review_reports WHERE owner=? AND cycle_id=?",
                (owner, cycle_id),
            ).fetchone()
            require(row is not None, "RSI_REVIEW_REPORT_REQUIRED")
            return {**json.loads(row[0]), "issue": json.loads(row[1]) if row[1] else None}

    def report_ready(self, owner, report):
        with self.ledger.connection() as db:
            return self._report_ready(db, owner, report)

    def _report_ready(self, db, owner, report):
        for cycle_id in report.get("source_cycles", [report["cycle_id"]]):
            cycle = db.execute(
                "SELECT report_json FROM rsi_cycles WHERE owner=? AND id=?", (owner, cycle_id)
            ).fetchone()
            if cycle is None or not json.loads(cycle[0]).get("daily_complete"):
                return False
        return True

    def _queue_report_issue(self, db, action):
        owner, cycle_id = action["owner"], action["payload"]["cycle_id"]
        original = json.loads(
            db.execute(
                "SELECT report_json FROM rsi_review_reports WHERE owner=? AND cycle_id=?",
                (owner, cycle_id),
            ).fetchone()[0]
        )
        report = original
        expected = original.get("expected_machines", [])
        if len(expected) > 1:
            members = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT report_json FROM rsi_review_reports WHERE owner=?", (owner,)
                )
            ]
            members = [
                r
                for r in members
                if r.get("group_id") == original["group_id"]
                and len(r.get("source_cycles", [])) == 1
            ]
            if {r["machine_id"] for r in members} != set(expected):
                return
            require(
                len(members) == len(expected)
                and all(set(r["expected_machines"]) == set(expected) for r in members),
                "RSI_PERIOD_REPORT_CONFLICT",
            )
            if not all(self._report_ready(db, owner, r) for r in members):
                return
            members.sort(key=lambda r: r["machine_id"])
            cycle_id = "period-" + original["group_id"]
            document = "# Roami RSI 全机复盘\n\n" + "\n\n".join(
                "## " + r["machine_id"] + "\n\n" + r["document"] for r in members
            )
            points = {p["id"]: p for r in members for p in r["points"]}
            report = {
                "cycle_id": cycle_id,
                "day": members[0]["day"],
                "group_id": original["group_id"],
                "expected_machines": expected,
                "source_cycles": [r["cycle_id"] for r in members],
                "sha256": digest(document),
                "document": document,
                "points": [points[k] for k in sorted(points)],
                "reviewer": "codex",
            }
            db.execute(
                "INSERT OR IGNORE INTO rsi_review_reports VALUES(?,?,?,NULL,?)",
                (owner, cycle_id, json.dumps(report), self.owner.clock()),
            )
            stored = json.loads(
                db.execute(
                    "SELECT report_json FROM rsi_review_reports WHERE owner=? AND cycle_id=?",
                    (owner, cycle_id),
                ).fetchone()[0]
            )
            require(stored == report, "RSI_PERIOD_REPORT_CONFLICT")
            for point in report["points"]:
                db.execute(
                    "INSERT OR IGNORE INTO rsi_report_items VALUES(?,?,?,?)",
                    (owner, cycle_id, digest([owner, point["id"]]), point["id"]),
                )
        if self._report_ready(db, owner, report):
            self.owner._enqueue(db, owner, "issue", cycle_id, {"cycle_id": cycle_id})

    def _attach_issue(self, db, action, result):
        cycle_id = action["payload"]["cycle_id"]
        row = db.execute(
            "SELECT report_json FROM rsi_review_reports WHERE owner=? AND cycle_id=?",
            (action["owner"], cycle_id),
        ).fetchone()
        require(row is not None, "RSI_REVIEW_REPORT_REQUIRED")
        report = json.loads(row[0])
        require(self._report_ready(db, action["owner"], report), "RSI_EVIDENCE_INCOMPLETE")
        issue = result.get("issue", {})

        require(
            issue.get("report_hash") == report["sha256"]
            and type(issue.get("number")) is int
            and issue["number"] > 0
            and isinstance(issue.get("repository"), str)
            and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", issue["repository"])
            and issue.get("url")
            == f"https://github.com/{issue['repository']}/issues/{issue['number']}",
            "RSI_ISSUE_PUBLICATION_REQUIRED",
        )
        db.execute(
            "UPDATE rsi_review_reports SET issue_json=? WHERE owner=? AND cycle_id=?",
            (json.dumps(issue), action["owner"], cycle_id),
        )
        order = {
            p["id"]: (p["priority"], i)
            for i, p in enumerate(issue.get("plan", {}).get("points", []))
        }
        for point in sorted(report["points"], key=lambda p: order.get(p["id"], ("P2", 0))):
            item_id = digest([action["owner"], point["id"]])
            row = db.execute(
                "SELECT state FROM rsi_improvements WHERE owner=? AND id=?",
                (action["owner"], item_id),
            ).fetchone()
            require(row is not None, "RSI_FINDING_REQUIRED")
            pending = db.execute(
                "SELECT 1 FROM rsi_actions WHERE owner=? AND kind='repair' AND json_extract(payload_json,'$.improvement_id')=? AND state IN ('queued','running','blocked','waiting_budget')",
                (action["owner"], item_id),
            ).fetchone()
            if row[0] in {"diagnosing", "reopened", "closed_fixed"} and not pending:
                db.execute(
                    "UPDATE rsi_improvements SET state='diagnosing',revision=revision+1,updated_ms=? WHERE owner=? AND id=?",
                    (self.owner.clock(), action["owner"], item_id),
                )
                self.owner._enqueue(
                    db,
                    action["owner"],
                    "repair",
                    item_id + ":" + cycle_id,
                    {
                        "improvement_id": item_id,
                        "finding": point["finding"],
                        "attempt": 1,
                        "issue": issue,
                        "point_id": point["id"],
                    },
                )

    def enqueue_issue_sync(self, owner, cycle_id):
        with self.ledger.connection() as db:
            reports = db.execute(
                "SELECT cycle_id FROM rsi_review_reports WHERE owner=? AND issue_json IS NOT NULL",
                (owner,),
            ).fetchall()
            for report in reports:
                self.owner._enqueue(
                    db, owner, "sync_issue", report[0] + ":" + cycle_id, {"cycle_id": report[0]}
                )
