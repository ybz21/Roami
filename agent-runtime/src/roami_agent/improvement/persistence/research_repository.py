"""Durable RSI handoffs; executor reports never close an improvement item."""

import json
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

from roami_agent.improvement.domain.contracts import digest, require
from roami_agent.improvement.integrations.spending_policy import uses_shared_model_limit
from roami_agent.improvement.persistence.research_configuration import ResearchConfiguration
from roami_agent.improvement.persistence.research_costs import ResearchCosts
from roami_agent.improvement.persistence.research_reports import ResearchReports
from roami_agent.protocol.identity import now_ms


class ResearchRepository:
    def __init__(self, ledger, *, clock=now_ms):
        self.ledger, self.clock = ledger, clock
        self.configuration = ResearchConfiguration(self)
        self.costs = ResearchCosts(self)
        self.reports = ResearchReports(self)

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
                    "AND (? OR EXISTS(SELECT 1 FROM rsi_budgets WHERE owner=? AND day=?))",
                    (
                        self.clock(),
                        owner,
                        day,
                        getattr(self, "model_proxy", None) is not None
                        or uses_shared_model_limit(self.ledger),
                        owner,
                        day,
                    ),
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
        if getattr(self, "model_proxy", None) is not None:
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
                from roami_agent.improvement.persistence.semantic_completion import (
                    complete_cycle_review,
                )

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
                    if not uses_shared_model_limit(self.ledger)
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

    def review_document(self, owner, cycle_id):
        with self.ledger.connection() as db:
            row = db.execute(
                "SELECT report_json FROM rsi_review_reports WHERE owner=? AND cycle_id=?",
                (owner, cycle_id),
            ).fetchone()
        return json.loads(row[0])["document"] if row else None

    def assert_action_owned(self, action):
        with self.ledger.connection() as db:
            self._owned_action(db, action)

    def retry_repair(self, action, finding, attempt):
        item_id = action["payload"].get("improvement_id", action["subject"])
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._owned_action(db, action)
            db.execute(
                "UPDATE rsi_actions SET state='done',error_code='RSI_CANDIDATE_REJECTED',lease=NULL,expires_ms=NULL WHERE id=?",
                (action["id"],),
            )
            # Keep the improvement subject; action identity includes an attempt in the kind key.
            identifier = self._enqueue(
                db,
                action["owner"],
                "repair",
                item_id + ":" + str(attempt),
                {
                    **{
                        k: action["payload"][k]
                        for k in ("issue", "point_id")
                        if k in action["payload"]
                    },
                    "finding": finding,
                    "attempt": attempt,
                    "improvement_id": item_id,
                },
            )
            db.execute(
                "UPDATE rsi_improvements SET state='diagnosing',revision=revision+1 WHERE id=? AND owner=?",
                (item_id, action["owner"]),
            )
            return identifier

    def settings(self, owner):
        return self.configuration.settings(owner)

    def configure(self, owner, raw):
        return self.configuration.configure(owner, raw)

    def configure_experiment(self, owner, raw):
        return self.configuration.configure_experiment(owner, raw)

    def operation_result(self, owner, key):
        return self.costs.operation_result(owner, key)

    def reserve_operation(self, owner, day, key, tokens):
        return self.costs.reserve_operation(owner, day, key, tokens)

    def settle_operation(self, owner, key, result):
        return self.costs.settle_operation(owner, key, result)

    def review_saved(self, owner, cycle_id):
        return self.costs.review_saved(owner, cycle_id)

    def save_review(self, owner, cycle_id, key, value):
        return self.costs.save_review(owner, cycle_id, key, value)

    def save_report(self, action, report):
        return self.reports.save_report(action, report)

    def report(self, owner, cycle_id):
        return self.reports.report(owner, cycle_id)

    def report_ready(self, owner, report):
        return self.reports.report_ready(owner, report)

    def _report_ready(self, db, owner, report):
        return self.reports._report_ready(db, owner, report)

    def _queue_report_issue(self, db, action):
        return self.reports._queue_report_issue(db, action)

    def _attach_issue(self, db, action, result):
        return self.reports._attach_issue(db, action, result)

    def enqueue_issue_sync(self, owner, cycle_id):
        return self.reports.enqueue_issue_sync(owner, cycle_id)
