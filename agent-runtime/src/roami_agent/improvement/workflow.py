"""Durable RSI handoffs; executor reports never close an improvement item."""

import json
import secrets
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from roami_agent.improvement.contracts import digest, require
from roami_agent.improvement.operation_accounting import assert_operation_costs_settled
from roami_agent.protocol.identity import now_ms

SCHEMA = """
CREATE TABLE IF NOT EXISTS rsi_research_settings (
 owner TEXT PRIMARY KEY, revision INTEGER NOT NULL, config_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rsi_actions (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, kind TEXT NOT NULL, subject TEXT NOT NULL,
 state TEXT NOT NULL, payload_json TEXT NOT NULL, result_json TEXT,
 created_ms INTEGER NOT NULL, due_ms INTEGER NOT NULL, lease TEXT, expires_ms INTEGER,
 error_code TEXT, UNIQUE(owner,kind,subject)
);
CREATE TABLE IF NOT EXISTS rsi_improvements (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, fingerprint TEXT NOT NULL,
 state TEXT NOT NULL, revision INTEGER NOT NULL, finding_json TEXT NOT NULL,
 data_json TEXT NOT NULL, updated_ms INTEGER NOT NULL, UNIQUE(owner,fingerprint)
);
CREATE TABLE IF NOT EXISTS rsi_improvement_events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, improvement_id TEXT,
 action_id TEXT NOT NULL, event TEXT NOT NULL, data_json TEXT NOT NULL, created_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS rsi_verify_receipts ON rsi_improvement_events(
 owner,json_extract(data_json,'$.verification_context.source_hash'),created_ms
) WHERE event='verify.completed';
CREATE TABLE IF NOT EXISTS rsi_operation_costs (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, day TEXT NOT NULL, reserved INTEGER NOT NULL,
 state TEXT NOT NULL, result_json TEXT
);
CREATE TABLE IF NOT EXISTS rsi_semantic_reviews (
 owner TEXT NOT NULL, cycle_id TEXT NOT NULL, trial_key TEXT NOT NULL,
 review_json TEXT NOT NULL, PRIMARY KEY(owner,cycle_id,trial_key)
);
CREATE TABLE IF NOT EXISTS rsi_code_targets (
 owner TEXT PRIMARY KEY, revision INTEGER NOT NULL, release_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rsi_code_observations (
 owner TEXT NOT NULL, improvement_id TEXT NOT NULL, cycle_id TEXT NOT NULL,
 day TEXT NOT NULL, passed INTEGER NOT NULL, PRIMARY KEY(owner,improvement_id,cycle_id)
);
CREATE TABLE IF NOT EXISTS rsi_review_reports (
 owner TEXT NOT NULL, cycle_id TEXT NOT NULL, report_json TEXT NOT NULL,
 issue_json TEXT, created_ms INTEGER NOT NULL, PRIMARY KEY(owner,cycle_id)
);
CREATE TABLE IF NOT EXISTS rsi_report_items (
 owner TEXT NOT NULL, cycle_id TEXT NOT NULL, improvement_id TEXT NOT NULL,
 point_id TEXT NOT NULL, PRIMARY KEY(owner,cycle_id,improvement_id)
);
"""
DEFAULTS = {
    "enabled": False,
    "repo": "",
    "base_commit": "",
    "allowed_paths": [],
    "model_tokens": 64000,
    "model_seconds": 180,
    "repair_executor": "codex",
    "validation_suite_id": "",
    "max_attempts": 2,
    "observation_days": 2,
}


class ResearchWorkflow:
    def __init__(self, ledger, *, clock=now_ms):
        self.ledger, self.clock = ledger, clock

    def settings(self, owner):
        with self.ledger.connection() as db:
            r = db.execute("SELECT * FROM rsi_research_settings WHERE owner=?", (owner,)).fetchone()
            value = {
                **DEFAULTS,
                **(json.loads(r["config_json"]) if r else {}),
                "revision": r["revision"] if r else 0,
            }
            if value["repair_executor"] == "native_patch":
                value["repair_executor"] = "codex"
                value["enabled"] = False
            return value

    def configure(self, owner, raw):
        require(isinstance(raw, dict) and set(raw) == {*DEFAULTS, "revision"})
        value = {k: raw[k] for k in DEFAULTS}
        require(type(value["enabled"]) is bool)
        require(value["repair_executor"] == "codex", "RSI_CODEX_REQUIRED")
        require(type(value["model_tokens"]) is int and 10000 <= value["model_tokens"] <= 100000)
        require(type(value["model_seconds"]) is int and 10 <= value["model_seconds"] <= 600)
        require(type(value["max_attempts"]) is int and 1 <= value["max_attempts"] <= 3)
        require(type(value["observation_days"]) is int and 2 <= value["observation_days"] <= 14)
        require(isinstance(value["allowed_paths"], list) and len(value["allowed_paths"]) <= 16)
        for p in value["allowed_paths"]:
            require(
                isinstance(p, str)
                and p.startswith("agent-runtime/src/roami_agent/")
                and p == Path(p).as_posix()
                and ".." not in Path(p).parts
                and not p.endswith("/")
            )
            require(
                not p.startswith("agent-runtime/src/roami_agent/improvement"),
                "RSI_PROTECTED_SOURCE",
            )
        require(isinstance(value["repo"], str) and isinstance(value["base_commit"], str))
        require(isinstance(value["validation_suite_id"], str))
        if value["enabled"]:
            require(
                Path(value["repo"]).is_absolute()
                and Path(value["repo"]).is_dir()
                and len(value["base_commit"]) == 40
                and bool(value["allowed_paths"]),
                "RSI_RESEARCH_SETUP_REQUIRED",
            )
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT revision FROM rsi_research_settings WHERE owner=?", (owner,)
            ).fetchone()
            revision = prior[0] if prior else 0
            require(
                type(raw["revision"]) is int and raw["revision"] == revision,
                "RSI_SETTINGS_CONFLICT",
            )
            db.execute(
                "INSERT INTO rsi_research_settings VALUES(?,?,?) ON CONFLICT(owner) "
                "DO UPDATE SET revision=excluded.revision,config_json=excluded.config_json",
                (owner, revision + 1, json.dumps(value)),
            )
        return {**value, "revision": revision + 1}

    def configure_experiment(self, owner, raw):
        fields = {"enabled", "model_tokens", "model_seconds", "max_attempts", "observation_days"}
        if getattr(self.ledger, "shared_daily_limit", False):
            public = fields - {"model_tokens"} | {"revision"}
            require(isinstance(raw, dict) and public <= set(raw) <= fields | {"revision"})
            value = self.configure(
                owner,
                {**self.settings(owner), **{key: val for key, val in raw.items() if key in public}},
            )
            return {key: val for key, val in value.items() if key in public}
        require(isinstance(raw, dict) and set(raw) == fields | {"revision"})
        return self.configure(owner, {**self.settings(owner), **raw})

    def _enqueue(self, db, owner, kind, subject, payload):
        action_id = digest([owner, kind, subject])
        db.execute(
            "INSERT OR IGNORE INTO rsi_actions VALUES(?,?,?,?,'queued',?,NULL,?,?,NULL,NULL,NULL)",
            (action_id, owner, kind, subject, json.dumps(payload), self.clock(), self.clock()),
        )
        return action_id

    def enqueue_review(self, owner, cycle_id):
        cycle = self.ledger.get(owner, cycle_id)
        require(
            cycle["state"] == "completed"
            and cycle["manifest"].get("formal_daily_suite")
            and cycle["report"].get("full_suite_complete"),
            "RSI_REVIEW_INCOMPLETE",
        )
        with self.ledger.connection() as db:
            return self._enqueue(db, owner, "review", cycle_id, {"cycle_id": cycle_id})

    def discover(self):
        with self.ledger.connection() as db:
            owners = [
                r[0]
                for r in db.execute(
                    "SELECT DISTINCT owner FROM rsi_actions WHERE state='waiting_budget'"
                )
            ]
        for owner in owners:
            day = self.day(owner)
            with self.ledger.connection() as db:
                db.execute(
                    "UPDATE rsi_actions SET state='queued',error_code=NULL,due_ms=? "
                    "WHERE owner=? AND state='waiting_budget' AND json_extract(payload_json,'$.budget_day')!=? "
                    "AND EXISTS(SELECT 1 FROM rsi_budgets WHERE owner=? AND day=?)",
                    (self.clock(), owner, day, owner, day),
                )
        with self.ledger.connection() as db:
            cycles = [
                dict(r)
                for r in db.execute(
                    "SELECT c.owner,c.id FROM rsi_cycles c JOIN rsi_research_settings s ON s.owner=c.owner "
                    "WHERE c.state='completed' AND json_extract(s.config_json,'$.enabled')=1 "
                    "AND json_extract(s.config_json,'$.repair_executor')='codex' "
                    "AND json_extract(c.report_json,'$.full_suite_complete')=1 "
                    "AND json_extract(c.manifest_json,'$.formal_daily_suite')=1 "
                    "AND (json_extract(c.manifest_json,'$.request_key')='daily' OR EXISTS "
                    "(SELECT 1 FROM rsi_requests r WHERE r.owner=c.owner AND r.cycle_id=c.id AND r.kind='manual')) "
                    "AND NOT EXISTS(SELECT 1 FROM rsi_actions a WHERE a.owner=c.owner "
                    "AND a.kind='review' AND a.subject=c.id) ORDER BY c.started_ms LIMIT 20"
                )
            ]
        for c in cycles:
            self.enqueue_review(c["owner"], c["id"])

    def day(self, owner):
        if getattr(self, "model_proxy", None) is not None and getattr(
            self.ledger, "shared_daily_limit", False
        ):
            return self.model_proxy.billing.period()[0]
        with self.ledger.connection() as db:
            row = db.execute(
                "SELECT value_json FROM rsi_preferences WHERE owner=?", (owner,)
            ).fetchone()
        zone = json.loads(row[0]).get("timezone", "Asia/Shanghai") if row else "Asia/Shanghai"
        return datetime.fromtimestamp(self.clock() / 1000, ZoneInfo(zone)).date().isoformat()

    def claim(self, *, lease_ms=60000):
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            # Reconcile expired work, but never replay an unknown paid operation.
            db.execute(
                "UPDATE rsi_actions SET state='queued',lease=NULL,expires_ms=NULL "
                "WHERE state='running' AND expires_ms<?",
                (self.clock(),),
            )
            row = db.execute(
                "SELECT a.* FROM rsi_actions a JOIN rsi_research_settings s ON s.owner=a.owner "
                "WHERE a.state='queued' AND a.due_ms<=? "
                "AND (a.kind='review' OR NOT EXISTS(SELECT 1 FROM rsi_actions active "
                "WHERE active.owner=a.owner AND active.state='running' AND active.kind!='review')) "
                "AND (a.kind!='repair' OR NOT EXISTS(SELECT 1 FROM rsi_improvements i WHERE i.owner=a.owner AND i.state IN ('verifying','ready','observing'))) "
                "AND (a.kind NOT IN ('repair','activate') OR NOT EXISTS(SELECT 1 FROM rsi_requests r WHERE r.owner=a.owner AND r.state IN ('queued','running','cancelling'))) "
                "AND json_extract(s.config_json,'$.repair_executor')='codex' "
                "AND json_extract(s.config_json,'$.enabled')=1 ORDER BY CASE a.kind WHEN 'review' THEN 0 WHEN 'issue' THEN 1 WHEN 'sync_issue' THEN 2 ELSE 3 END,a.created_ms,a.rowid LIMIT 1",
                (self.clock(),),
            ).fetchone()
            if not row:
                return None
            lease = secrets.token_hex(16)
            db.execute(
                "UPDATE rsi_actions SET state='running',lease=?,expires_ms=? WHERE id=?",
                (lease, self.clock() + lease_ms, row["id"]),
            )
            return {**dict(row), "lease": lease, "payload": json.loads(row["payload_json"])}

    def heartbeat(self, action):
        with self.ledger.connection() as db:
            n = db.execute(
                "UPDATE rsi_actions SET expires_ms=? WHERE id=? AND owner=? "
                "AND lease=? AND state='running' AND expires_ms>=?",
                (
                    self.clock() + 60000,
                    action["id"],
                    action["owner"],
                    action["lease"],
                    self.clock(),
                ),
            )
            require(n.rowcount == 1, "RSI_ACTION_LEASE_LOST")

    def _owned_action(self, db, action):
        row = db.execute(
            "SELECT a.* FROM rsi_actions a JOIN rsi_research_settings s ON s.owner=a.owner "
            "WHERE a.id=? AND a.owner=? AND a.lease=? "
            "AND a.state='running' AND a.expires_ms>=? AND json_extract(s.config_json,'$.enabled')=1 "
            "AND json_extract(s.config_json,'$.repair_executor')='codex'",
            (action["id"], action["owner"], action["lease"], self.clock()),
        ).fetchone()
        require(row is not None, "RSI_ACTION_LEASE_LOST")

    def complete(self, action, result, *, next_kind=None, payload=None, item_state=None):
        require(
            item_state in {None, "verifying", "ready", "observing"},
            "RSI_INDEPENDENT_CLOSURE_REQUIRED",
        )
        item_id = action["payload"].get("improvement_id", action["subject"])
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._owned_action(db, action)
            if action["kind"] == "review":
                from roami_agent.improvement.semantic_completion import complete_cycle_review

                complete_cycle_review(db, action["owner"], action["payload"]["cycle_id"])
                require(
                    db.execute(
                        "SELECT 1 FROM rsi_review_reports WHERE owner=? AND cycle_id=?",
                        (action["owner"], action["payload"]["cycle_id"]),
                    ).fetchone(),
                    "RSI_REVIEW_REPORT_REQUIRED",
                )
                next_kind = None
                self._queue_report_issue(db, action)
            if action["kind"] == "issue":
                self._attach_issue(db, action, result)
            db.execute(
                "UPDATE rsi_actions SET state='done',result_json=?,error_code=?,lease=NULL,expires_ms=NULL WHERE id=?",
                (
                    json.dumps(result, allow_nan=False),
                    "RSI_OBSERVATION_" + result["observation"]["reason"].upper()
                    if result.get("observation", {}).get("reason")
                    else None,
                    action["id"],
                ),
            )
            if item_state:
                db.execute(
                    "UPDATE rsi_improvements SET state=?,revision=revision+1,data_json=?,updated_ms=? "
                    "WHERE id=? AND owner=?",
                    (
                        item_state,
                        json.dumps(result),
                        self.clock(),
                        item_id,
                        action["owner"],
                    ),
                )
            if next_kind:
                self._enqueue(db, action["owner"], next_kind, action["subject"], payload or result)
            db.execute(
                "INSERT INTO rsi_improvement_events(owner,improvement_id,action_id,event,data_json,created_ms) "
                "VALUES(?,?,?,?,?,?)",
                (
                    action["owner"],
                    None if action["kind"] in {"review", "issue", "sync_issue"} else item_id,
                    action["id"],
                    action["kind"] + ".completed",
                    json.dumps(result),
                    self.clock(),
                ),
            )

    def block(self, action, code):
        item_id = action["payload"].get("improvement_id", action["subject"])
        day = self.day(action["owner"])
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._owned_action(db, action)
            state = (
                "waiting_budget"
                if code in {"RSI_DAILY_BUDGET", "RSI_FULL_SUITE_BUDGET", "MODEL_PROXY_DAILY_LIMIT"}
                else "blocked"
            )
            db.execute(
                "UPDATE rsi_actions SET state=?,error_code=?,lease=NULL,expires_ms=NULL WHERE id=?",
                (state, code, action["id"]),
            )
            if state == "waiting_budget":
                db.execute(
                    "UPDATE rsi_actions SET payload_json=json_set(payload_json,'$.budget_day',?) WHERE id=?",
                    (day, action["id"]),
                )
            if action["kind"] != "review":
                db.execute(
                    "UPDATE rsi_improvements SET state=?,revision=revision+1,updated_ms=? WHERE id=? AND owner=?",
                    (state, self.clock(), item_id, action["owner"]),
                )

    def resume(self, owner, action_id):
        with self.ledger.connection() as db:
            row = db.execute(
                "SELECT * FROM rsi_actions WHERE id=? AND owner=?", (action_id, owner)
            ).fetchone()
            require(row is not None, "RSI_ACTION_NOT_FOUND")
            require(row["state"] in {"blocked", "waiting_budget"}, "RSI_ACTION_NOT_BLOCKED")
            require(
                not db.execute(
                    "SELECT 1 FROM rsi_operation_costs WHERE owner=? AND id LIKE ? "
                    "AND state!='completed'",
                    (owner, action_id + ":%"),
                ).fetchone(),
                "RSI_UNKNOWN_OPERATION_REQUIRES_RECONCILIATION",
            )
            db.execute(
                "UPDATE rsi_actions SET state='queued',due_ms=?,error_code=NULL WHERE id=?",
                (self.clock(), action_id),
            )
        return {"id": action_id, "state": "queued"}

    def record_findings(self, action, findings):
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._owned_action(db, action)
            for f in findings:
                fingerprint = digest([f["mechanism"], sorted(f["paths"])])
                item_id = digest([action["owner"], fingerprint])
                db.execute(
                    "INSERT OR IGNORE INTO rsi_improvements VALUES(?,?,?,'diagnosing',1,?,'{}',?)",
                    (item_id, action["owner"], fingerprint, json.dumps(f), self.clock()),
                )
                db.execute(
                    "INSERT INTO rsi_improvement_events(owner,improvement_id,action_id,event,data_json,created_ms) "
                    "VALUES(?,?,?,'evidence.added',?,?)",
                    (action["owner"], item_id, action["id"], json.dumps(f), self.clock()),
                )

    def save_report(self, action, report):
        self.record_findings(action, [p["finding"] for p in report["points"]])
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._owned_action(db, action)
            prior = db.execute(
                "SELECT report_json FROM rsi_review_reports WHERE owner=? AND cycle_id=?",
                (action["owner"], report["cycle_id"]),
            ).fetchone()
            require(prior is None or json.loads(prior[0]) == report, "RSI_REVIEW_REPORT_CONFLICT")
            db.execute(
                "INSERT OR IGNORE INTO rsi_review_reports VALUES(?,?,?,NULL,?)",
                (action["owner"], report["cycle_id"], json.dumps(report), self.clock()),
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
                (owner, cycle_id, json.dumps(report), self.clock()),
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
            self._enqueue(db, owner, "issue", cycle_id, {"cycle_id": cycle_id})

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
        import re

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
                    (self.clock(), action["owner"], item_id),
                )
                self._enqueue(
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
                self._enqueue(
                    db, owner, "sync_issue", report[0] + ":" + cycle_id, {"cycle_id": report[0]}
                )

    def reserve_operation(self, owner, day, key, tokens):
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT * FROM rsi_operation_costs WHERE id=? AND owner=?", (key, owner)
            ).fetchone()
            if prior:
                require(
                    prior["state"] == "completed", "RSI_UNKNOWN_OPERATION_REQUIRES_RECONCILIATION"
                )
                return json.loads(prior["result_json"])
            assert_operation_costs_settled(db, owner)
            budget = db.execute(
                "SELECT * FROM rsi_budgets WHERE owner=? AND day=?", (owner, day)
            ).fetchone()
            require(
                getattr(self.ledger, "shared_daily_limit", False)
                or budget
                and budget["tokens_reserved"] + tokens <= budget["tokens_limit"],
                "RSI_DAILY_BUDGET",
            )
            db.execute(
                "UPDATE rsi_budgets SET tokens_reserved=tokens_reserved+? WHERE owner=? AND day=?",
                (tokens, owner, day),
            )
            db.execute(
                "INSERT INTO rsi_operation_costs VALUES(?,?,?,?,'running',NULL)",
                (key, owner, day, tokens),
            )
        return None

    def settle_operation(self, owner, key, result):
        tokens = result.get("value", {}).get("metrics", {}).get("tokens")
        require(tokens is None or type(tokens) is int and tokens >= 0, "RSI_INVALID_MEASUREMENT")
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT reserved,day FROM rsi_operation_costs WHERE owner=? AND id=? AND state='running'",
                (owner, key),
            ).fetchone()
            require(row is not None, "RSI_OPERATION_CONFLICT")
            if tokens is not None:
                db.execute(
                    "UPDATE rsi_budgets SET tokens_reserved=tokens_reserved+? WHERE owner=? AND day=?",
                    (tokens - row["reserved"], owner, row["day"]),
                )
            db.execute(
                "UPDATE rsi_operation_costs SET state=?,result_json=? WHERE owner=? AND id=? AND state='running'",
                (
                    "completed" if tokens is not None else "unknown",
                    json.dumps(result, allow_nan=False),
                    owner,
                    key,
                ),
            )

    def review_saved(self, owner, cycle_id):
        with self.ledger.connection() as db:
            return {
                r["trial_key"]: json.loads(r["review_json"])
                for r in db.execute(
                    "SELECT * FROM rsi_semantic_reviews WHERE owner=? AND cycle_id=?",
                    (owner, cycle_id),
                )
            }

    def save_review(self, owner, cycle_id, key, value):
        with self.ledger.connection() as db:
            db.execute(
                "INSERT OR IGNORE INTO rsi_semantic_reviews VALUES(?,?,?,?)",
                (owner, cycle_id, key, json.dumps(value)),
            )

    def snapshot(self, owner):
        settings = self.settings(owner)
        day = self.day(owner)
        with self.ledger.connection() as db:
            cost = db.execute(
                "SELECT COALESCE(SUM(reserved),0) AS reserved, "
                "COALESCE(SUM(json_extract(result_json,'$.value.metrics.tokens')),0) AS used, "
                "COALESCE(SUM(state!='completed'),0) AS unknown FROM rsi_operation_costs WHERE owner=? AND day=?",
                (owner, day),
            ).fetchone()
            return {
                "settings": {
                    key: val
                    for key, val in settings.items()
                    if not getattr(self.ledger, "shared_daily_limit", False)
                    or key
                    in {"revision", "enabled", "model_seconds", "max_attempts", "observation_days"}
                },
                "model_cost": {
                    "day": day,
                    "reserved_tokens": cost["reserved"],
                    "observed_tokens": cost["used"],
                    "total_tokens": None if cost["unknown"] else cost["used"],
                },
                "review_coverage": [
                    dict(r)
                    for r in db.execute(
                        "SELECT cycle_id,COUNT(*) AS reviewed FROM rsi_semantic_reviews WHERE owner=? GROUP BY cycle_id ORDER BY rowid DESC LIMIT 30",
                        (owner,),
                    )
                ],
                "actions": [
                    {k: r[k] for k in ("id", "kind", "subject", "state", "error_code", "due_ms")}
                    for r in db.execute(
                        "SELECT * FROM rsi_actions WHERE owner=? ORDER BY created_ms DESC LIMIT 100",
                        (owner,),
                    )
                ],
                "reports": [
                    {
                        "cycle_id": r["cycle_id"],
                        "day": json.loads(r["report_json"])["day"],
                        "points": len(json.loads(r["report_json"])["points"]),
                        "issueUrl": json.loads(r["issue_json"])["url"] if r["issue_json"] else None,
                    }
                    for r in db.execute(
                        "SELECT * FROM rsi_review_reports WHERE owner=? AND (COALESCE(json_array_length(json_extract(report_json,'$.expected_machines')),0)<=1 OR json_array_length(json_extract(report_json,'$.source_cycles'))>1) ORDER BY created_ms DESC LIMIT 30",
                        (owner,),
                    )
                ],
                "improvements": [
                    {
                        **{k: r[k] for k in ("id", "state", "revision", "updated_ms")},
                        "title": json.loads(r["finding_json"])["fact"][:100],
                        "reviewUrl": json.loads(r["data_json"])
                        .get("review_publication", {})
                        .get("url"),
                    }
                    for r in db.execute(
                        "SELECT * FROM rsi_improvements WHERE owner=? ORDER BY updated_ms DESC LIMIT 100",
                        (owner,),
                    )
                ],
            }
