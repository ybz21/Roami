"""Owner-scoped runs, node attempts, artifacts and repeatable issue observations."""

import json
import re
import secrets

from roami_agent.improvement.domain.admission_blocking import MODEL_AUTHENTICATION_BLOCKERS
from roami_agent.improvement.domain.contracts import digest, require
from roami_agent.improvement.domain.run_configuration import DEFAULTS, STAGES
from roami_agent.improvement.integrations.spending_policy import uses_shared_model_limit
from roami_agent.improvement.persistence.run_artifacts import RunArtifacts
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms


class RunRepository:
    def __init__(self, ledger):
        self.ledger = ledger
        self.root = ledger.path.parent / "pipeline-artifacts"
        self.artifacts = RunArtifacts(ledger, self)

    def settings(self, owner):
        with self.ledger.connection() as db:
            row = db.execute(
                "SELECT value_json FROM rsi_pipeline_settings WHERE owner=?", (owner,)
            ).fetchone()
            return {**DEFAULTS, **(json.loads(row[0]) if row else {})}

    def configure(self, owner, value):
        shared = uses_shared_model_limit(self.ledger)
        if shared:
            require(
                isinstance(value, dict)
                and {"revision", "auto_publish"} <= set(value) <= set(DEFAULTS),
                "RSI_INVALID_SETTINGS",
            )
            value = {
                **self.settings(owner),
                "revision": value["revision"],
                "auto_publish": value["auto_publish"],
            }
        require(
            isinstance(value, dict) and {"revision"} <= set(value) <= set(DEFAULTS),
            "RSI_INVALID_SETTINGS",
        )
        value = {**self.settings(owner), **value}
        for role in ("main", "worker"):
            cap = value[role + "_output_tokens"]
            require(
                cap is None or type(cap) is int and 512 <= cap <= 1_000_000,
                "RSI_POLICY_OUT_OF_RANGE",
            )
        from roami_agent.providers.reasoning_effort import EFFORTS

        for role in ("main", "worker", "memory"):
            model, effort = value[role + "_model"], value[role + "_reasoning_effort"]
            require(
                model is None
                or isinstance(model, str)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}", model),
                "RSI_INVALID_SETTINGS",
            )
            require(
                effort is None or isinstance(effort, str) and effort in EFFORTS,
                "RSI_INVALID_SETTINGS",
            )
        require(type(value["auto_publish"]) is bool)
        for key, lower, upper in (
            ("daily_tokens", 10000, 100000000),
            ("generation_tokens", 10000, 2000000),
            ("codex_tokens", 20000, 100000),
            ("output_tokens", 4096, 16384),
            ("memory_output_tokens", 1024, 8192),
        ):
            require(
                type(value[key]) is int and lower <= value[key] <= upper, "RSI_POLICY_OUT_OF_RANGE"
            )
        require(
            value["generation_tokens"] + 2 * value["codex_tokens"] <= value["daily_tokens"],
            "RSI_DAILY_BUDGET",
        )
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT value_json FROM rsi_pipeline_settings WHERE owner=?", (owner,)
            ).fetchone()
            prior = json.loads(old[0]) if old else DEFAULTS
            require(
                type(value["revision"]) is int and value["revision"] == prior["revision"],
                "RSI_SETTINGS_CONFLICT",
            )
            if value["daily_tokens"] != prior["daily_tokens"] and not getattr(
                self.ledger, "shared_daily_limit", False
            ):
                from datetime import datetime
                from zoneinfo import ZoneInfo

                prefs = db.execute(
                    "SELECT value_json FROM rsi_preferences WHERE owner=?", (owner,)
                ).fetchone()
                timezone = (
                    json.loads(prefs[0]).get("timezone", "Asia/Shanghai")
                    if prefs
                    else "Asia/Shanghai"
                )
                day = datetime.now(ZoneInfo(timezone)).date().isoformat()
                budget = db.execute(
                    "SELECT tokens_reserved FROM rsi_budgets WHERE owner=? AND day=?", (owner, day)
                ).fetchone()
                require(not budget or budget[0] <= value["daily_tokens"], "RSI_DAILY_BUDGET")
                db.execute(
                    "UPDATE rsi_budgets SET tokens_limit=? WHERE owner=? AND day=?",
                    (value["daily_tokens"], owner, day),
                )
            result = {**value, "revision": value["revision"] + 1}
            db.execute(
                "INSERT OR REPLACE INTO rsi_pipeline_settings VALUES(?,?)",
                (owner, json.dumps(result)),
            )
        return {
            key: val
            for key, val in result.items()
            if not shared or key in {"revision", "auto_publish"}
        }

    @staticmethod
    def create_tx(db, owner, run_id, request_key, mode, snapshot):
        exists = db.execute(
            "SELECT id FROM rsi_pipeline_runs WHERE owner=? AND request_key=?", (owner, request_key)
        ).fetchone()
        if exists:
            return exists[0]
        timestamp = now_ms()
        db.execute(
            "INSERT INTO rsi_pipeline_runs VALUES(?,?,?,?, 'queued',?,?,?,NULL,NULL,NULL,NULL,NULL)",
            (run_id, owner, request_key, mode, timestamp, timestamp, json.dumps(snapshot)),
        )
        for node in STAGES:
            config = (
                snapshot.get("pipeline", {}) if node == "evaluate" else snapshot.get("research", {})
            )
            db.execute(
                "INSERT INTO rsi_pipeline_nodes VALUES(?,?,1,'pending',?,NULL,NULL,NULL)",
                (run_id, node, json.dumps(config)),
            )
        return run_id

    def create(self, owner, key, mode, snapshot):
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            return self.create_tx(db, owner, digest([owner, key]), key, mode, snapshot)

    def node(self, owner, run_id, node, state, error=None):
        require(
            node in STAGES
            and state
            in {"pending", "running", "succeeded", "failed", "blocked", "skipped", "unknown"}
        )
        with self.ledger.connection() as db:
            require(
                db.execute(
                    "SELECT 1 FROM rsi_pipeline_runs WHERE id=? AND owner=?", (run_id, owner)
                ).fetchone(),
                "RSI_RUN_NOT_FOUND",
            )
            attempt = db.execute(
                "SELECT MAX(attempt) FROM rsi_pipeline_nodes WHERE run_id=? AND node=?",
                (run_id, node),
            ).fetchone()[0]
            db.execute(
                "UPDATE rsi_pipeline_nodes SET state=?,started_ms=CASE WHEN ?='running' THEN ? ELSE started_ms END,finished_ms=CASE WHEN ?!='running' THEN ? ELSE NULL END,error_code=? WHERE run_id=? AND node=? AND attempt=?",
                (state, state, now_ms(), state, now_ms(), error, run_id, node, attempt),
            )
            db.execute(
                "INSERT INTO rsi_pipeline_events(run_id,node,state,detail,created_ms) VALUES(?,?,?,?,?)",
                (run_id, node, state, error, now_ms()),
            )
            db.execute("UPDATE rsi_pipeline_runs SET updated_ms=? WHERE id=?", (now_ms(), run_id))

    def set_state(self, owner, run_id, state, summary=None):
        with self.ledger.connection() as db:
            require(
                db.execute(
                    "UPDATE rsi_pipeline_runs SET state=?,updated_ms=?,summary_json=COALESCE(?,summary_json) WHERE owner=? AND id=?",
                    (
                        state,
                        now_ms(),
                        json.dumps(summary) if summary is not None else None,
                        owner,
                        run_id,
                    ),
                ).rowcount
                == 1,
                "RSI_RUN_NOT_FOUND",
            )

    def case(self, owner, run_id, outcome):
        with self.ledger.connection() as db:
            require(
                db.execute(
                    "SELECT 1 FROM rsi_pipeline_runs WHERE id=? AND owner=?", (run_id, owner)
                ).fetchone(),
                "RSI_RUN_NOT_FOUND",
            )
            db.execute(
                "INSERT OR REPLACE INTO rsi_pipeline_cases VALUES(?,?,?,?)",
                (run_id, outcome["case_id"], outcome["source_hash"], json.dumps(outcome)),
            )

    def observations(self, owner, run_id):
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            run = db.execute(
                "SELECT created_ms FROM rsi_pipeline_runs WHERE id=? AND owner=?", (run_id, owner)
            ).fetchone()
            require(run is not None, "RSI_RUN_NOT_FOUND")
            cases = {
                r["case_id"]: json.loads(r["result_json"])
                for r in db.execute("SELECT * FROM rsi_pipeline_cases WHERE run_id=?", (run_id,))
            }
            observed = {}
            for case in cases.values():
                authentication = next(
                    (
                        code
                        for code in MODEL_AUTHENTICATION_BLOCKERS
                        if case.get("state") == "blocked" and code in case["signals"]
                    ),
                    None,
                )
                observed[case["case_id"]] = [authentication] if authentication else case["signals"]
            for case in cases.values():
                if case.get("blocked_by"):
                    continue
                for signal in observed[case["case_id"]]:
                    if signal in {"MODEL_HTTP_402", "MODEL_PROXY_DAILY_LIMIT"}:
                        continue
                    ident = digest([owner, case["case_id"], signal])
                    db.execute(
                        "INSERT INTO rsi_pipeline_issues VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated_ms=excluded.updated_ms",
                        (ident, owner, case["case_id"], signal, now_ms(), now_ms()),
                    )
            for issue in db.execute(
                "SELECT * FROM rsi_pipeline_issues WHERE owner=?", (owner,)
            ).fetchall():
                case = cases.get(issue["case_id"])
                prior = db.execute(
                    "SELECT c.source_hash FROM rsi_pipeline_observations o JOIN rsi_pipeline_cases c ON c.run_id=o.run_id AND c.case_id=? JOIN rsi_pipeline_runs r ON r.id=o.run_id WHERE o.issue_id=? AND r.owner=? AND (r.created_ms<? OR (r.created_ms=? AND r.id<?)) ORDER BY r.created_ms DESC,r.id DESC LIMIT 1",
                    (
                        issue["case_id"],
                        issue["id"],
                        owner,
                        run["created_ms"],
                        run["created_ms"],
                        run_id,
                    ),
                ).fetchone()
                if prior is None and (
                    case is None or issue["code"] not in observed[case["case_id"]]
                ):
                    db.execute(
                        "DELETE FROM rsi_pipeline_observations WHERE run_id=? AND issue_id=?",
                        (run_id, issue["id"]),
                    )
                    continue
                status = (
                    "not_tested"
                    if case is None
                    else "unverified"
                    if case.get("blocked_by")
                    else "present"
                    if issue["code"] in observed[case["case_id"]]
                    else "not_comparable"
                    if prior and prior[0] != case["source_hash"]
                    else "not_reproduced"
                    if case["passed"]
                    and not case["pending"]
                    and case["metrics"].get("tokens") is not None
                    else "unverified"
                )
                evidence = {
                    "case_state": case["state"] if case else None,
                    "source_hash": case["source_hash"] if case else None,
                }
                db.execute(
                    "INSERT OR REPLACE INTO rsi_pipeline_observations VALUES(?,?,?,?)",
                    (run_id, issue["id"], status, json.dumps(evidence)),
                )

    def get(self, owner, run_id):
        with self.ledger.connection() as db:
            run = db.execute(
                "SELECT * FROM rsi_pipeline_runs WHERE owner=? AND id=?", (owner, run_id)
            ).fetchone()
            if run is None:
                raise DomainError("RSI_RUN_NOT_FOUND", 404)
            value = {
                k: run[k] for k in ("id", "mode", "state", "created_ms", "updated_ms", "cycle_id")
            }
            value.update(
                snapshot=json.loads(run["snapshot_json"]),
                summary=json.loads(run["summary_json"]) if run["summary_json"] else None,
                issue=json.loads(run["issue_json"]) if run["issue_json"] else None,
            )
            costs = db.execute(
                "SELECT reserved,state,result_json FROM rsi_pipeline_costs WHERE owner=? AND run_id=?",
                (owner, run_id),
            ).fetchall()
            if costs:
                value["summary"] = {
                    **(value["summary"] or {}),
                    "codex_tokens": sum(
                        json.loads(c["result_json"])["value"]["metrics"]["tokens"] for c in costs
                    )
                    if all(c["state"] == "completed" for c in costs)
                    else None,
                }
            value["nodes"] = [
                dict(r) | {"config": json.loads(r["config_json"])}
                for r in db.execute(
                    "SELECT * FROM rsi_pipeline_nodes WHERE run_id=? ORDER BY node,attempt",
                    (run_id,),
                )
            ]
            for n in value["nodes"]:
                del n["config_json"]
            value["cases"] = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT result_json FROM rsi_pipeline_cases WHERE run_id=? ORDER BY case_id",
                    (run_id,),
                )
            ]
            value["artifacts"] = [
                {k: r[k] for k in ("id", "node", "name", "sha256", "bytes")}
                for r in db.execute(
                    "SELECT * FROM rsi_pipeline_artifacts WHERE run_id=?", (run_id,)
                )
            ]
            value["issues"] = [
                dict(r)
                for r in db.execute(
                    "SELECT i.id,i.case_id,i.code,o.status FROM rsi_pipeline_observations o JOIN rsi_pipeline_issues i ON i.id=o.issue_id WHERE o.run_id=? AND i.owner=? ORDER BY i.case_id,i.code",
                    (run_id, owner),
                )
            ]
        return value

    def claim_report(self):
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE rsi_pipeline_nodes SET state='unknown',error_code='RSI_WORKER_RESTARTED',finished_ms=? WHERE state='running' AND run_id IN (SELECT id FROM rsi_pipeline_runs WHERE state='reviewing' AND expires_ms<?)",
                (now_ms(), now_ms()),
            )
            db.execute(
                "UPDATE rsi_pipeline_runs SET state='blocked',lease=NULL WHERE state='reviewing' AND expires_ms<?",
                (now_ms(),),
            )
            r = db.execute(
                "SELECT * FROM rsi_pipeline_runs WHERE state='report_queued' ORDER BY created_ms LIMIT 1"
            ).fetchone()
            if not r:
                return None
            lease = secrets.token_hex(16)
            db.execute(
                "UPDATE rsi_pipeline_runs SET state='reviewing',lease=?,expires_ms=? WHERE id=?",
                (lease, now_ms() + 900000, r["id"]),
            )
            return {"id": r["id"], "owner": r["owner"], "lease": lease}

    def freeze_context(self, owner, run_id, context):
        require(set(context) == {"source_hash", "model_hash", "environment_hash", "judge_hash"})
        require(
            all(
                isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)
                for value in context.values()
            )
        )
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT snapshot_json FROM rsi_pipeline_runs WHERE id=? AND owner=?",
                (run_id, owner),
            ).fetchone()
            require(row is not None, "RSI_RUN_NOT_FOUND")
            snapshot = json.loads(row[0])
            require(
                "comparison_context" not in snapshot or snapshot["comparison_context"] == context,
                "RSI_COMPARISON_CONTEXT_CHANGED",
            )
            snapshot["comparison_context"] = context
            snapshot.setdefault("context_frozen_ms", now_ms())
            db.execute(
                "UPDATE rsi_pipeline_runs SET snapshot_json=? WHERE id=? AND owner=?",
                (json.dumps(snapshot), run_id, owner),
            )

    def queue_report(self, owner, run_id, summary, *, reserve=False):
        value = self.get(owner, run_id)
        if reserve:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            from roami_agent.improvement.domain.evaluation_configuration import (
                DEFAULTS as EVALUATION_DEFAULTS,
            )

            config = value["snapshot"]["pipeline"]
            prefs = value["snapshot"].get("preferences", {})
            day = datetime.now(ZoneInfo(prefs.get("timezone", "Asia/Shanghai"))).date().isoformat()
            with self.ledger.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT OR IGNORE INTO rsi_budgets VALUES(?,?,?,?,0,0)",
                    (
                        owner,
                        day,
                        prefs.get("daily_tokens") or config["daily_tokens"],
                        prefs.get("daily_episodes", EVALUATION_DEFAULTS["daily_episodes"]) or 10000,
                    ),
                )
                budget = db.execute(
                    "SELECT * FROM rsi_budgets WHERE owner=? AND day=?", (owner, day)
                ).fetchone()
                amount = config["codex_tokens"] * 2
                if (
                    not uses_shared_model_limit(self.ledger)
                    and budget["tokens_reserved"] + amount > budget["tokens_limit"]
                ):
                    db.execute(
                        "UPDATE rsi_pipeline_runs SET state='blocked',summary_json=? WHERE id=? AND owner=?",
                        (json.dumps(summary), run_id, owner),
                    )
                    db.execute(
                        "UPDATE rsi_pipeline_nodes SET state='blocked',error_code='RSI_DAILY_BUDGET' WHERE run_id=? AND node='review'",
                        (run_id,),
                    )
                    return
                db.execute(
                    "UPDATE rsi_budgets SET tokens_reserved=tokens_reserved+? WHERE owner=? AND day=?",
                    (amount, owner, day),
                )
        self.set_state(owner, run_id, "report_queued", {**summary, "report_admitted": True})

    def resume(self, owner, run_id):
        value = self.get(owner, run_id)
        require(value["state"] == "blocked", "RSI_ACTION_NOT_RESUMABLE")
        if (
            value["mode"] != "diagnostic"
            and not value["snapshot"].get("imported")
            and not (value["summary"] or {}).get("report_admitted")
        ):
            self.queue_report(owner, run_id, value["summary"] or {}, reserve=True)
            value = self.get(owner, run_id)
            require(value["state"] == "report_queued", "RSI_DAILY_BUDGET")
        require(value["state"] in {"blocked", "report_queued"}, "RSI_ACTION_NOT_RESUMABLE")
        with self.ledger.connection() as db:
            require(
                not db.execute(
                    "SELECT 1 FROM rsi_pipeline_costs WHERE owner=? AND run_id=? AND state!='completed'",
                    (owner, run_id),
                ).fetchone(),
                "RSI_UNKNOWN_OPERATION_REQUIRES_RECONCILIATION",
            )
            for node in value["nodes"]:
                if node["state"] in {"blocked", "unknown"} and node["node"] in {"review", "issue"}:
                    latest = max(n["attempt"] for n in value["nodes"] if n["node"] == node["node"])
                    if latest == node["attempt"]:
                        db.execute(
                            "INSERT INTO rsi_pipeline_nodes VALUES(?,?,?,'pending',?,NULL,NULL,NULL)",
                            (run_id, node["node"], latest + 1, json.dumps(node["config"])),
                        )
            db.execute(
                "UPDATE rsi_pipeline_runs SET state='report_queued',updated_ms=? WHERE owner=? AND id=?",
                (now_ms(), owner, run_id),
            )
        return {"id": run_id}

    def directory(self, owner, run_id):
        return self.artifacts.directory(owner, run_id)

    def artifact(self, owner, run_id, node, name, value):
        return self.artifacts.artifact(owner, run_id, node, name, value)

    def read_artifact(self, owner, run_id, artifact_id):
        return self.artifacts.read_artifact(owner, run_id, artifact_id)

    def request(self, owner, run_id):
        with self.ledger.connection() as db:
            row = db.execute(
                "SELECT * FROM rsi_requests WHERE owner=? AND id=?", (owner, run_id)
            ).fetchone()
        return dict(row) if row else None

    def attach_cycle(self, owner, run_id, cycle_id):
        with self.ledger.connection() as db:
            db.execute(
                "UPDATE rsi_pipeline_runs SET cycle_id=? WHERE id=? AND owner=?",
                (cycle_id, run_id, owner),
            )

    def research_enabled(self, owner):
        with self.ledger.connection() as db:
            row = db.execute(
                "SELECT config_json FROM rsi_research_settings WHERE owner=?", (owner,)
            ).fetchone()
        return bool(row and json.loads(row[0]).get("enabled"))

    def attach_request(self, request, snapshot):
        with self.ledger.connection() as db:
            self.create_tx(
                db, request["owner"], request["id"], request["id"], request["kind"], snapshot
            )

    def freeze_case_definitions(self, owner, run_id, suite, identities):
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT snapshot_json FROM rsi_pipeline_runs WHERE owner=? AND id=?",
                (owner, run_id),
            ).fetchone()
            require(row is not None, "RSI_RUN_NOT_FOUND")
            snapshot = json.loads(row[0])
            require(snapshot["suite_hash"] == suite["content_hash"], "RSI_SUITE_HASH_MISMATCH")
            cases = {case["id"]: case for case in suite["cases"]}
            ids = snapshot.get("case_ids") or list(cases)
            require(
                len(set(ids)) == len(ids)
                and set(ids) <= set(cases)
                and (not snapshot.get("formal_daily") or ids == list(cases)),
                "RSI_CASES_CHANGED",
            )
            snapshot.update(
                case_ids=ids,
                source_case_hashes={ident: digest(cases[ident]) for ident in ids},
            )
            if "case_definitions" not in snapshot:
                snapshot["case_definitions"] = {ident: identities[ident] for ident in ids}
            db.execute(
                "UPDATE rsi_pipeline_runs SET snapshot_json=? WHERE owner=? AND id=?",
                (json.dumps(snapshot), owner, run_id),
            )

    def list_overview(self, owner):
        with self.ledger.connection() as db:
            runs = [
                {
                    **{k: r[k] for k in ("id", "mode", "state", "created_ms", "updated_ms")},
                    "summary": json.loads(r["summary_json"]) if r["summary_json"] else None,
                    "issue": json.loads(r["issue_json"]) if r["issue_json"] else None,
                }
                for r in db.execute(
                    "SELECT * FROM rsi_pipeline_runs WHERE owner=? ORDER BY created_ms DESC LIMIT 30",
                    (owner,),
                )
            ]
            issues = [
                dict(r)
                for r in db.execute(
                    "SELECT i.*, (SELECT o.status FROM rsi_pipeline_observations o JOIN rsi_pipeline_runs r ON r.id=o.run_id WHERE o.issue_id=i.id ORDER BY r.created_ms DESC LIMIT 1) AS latest_status, (SELECT o.run_id FROM rsi_pipeline_observations o JOIN rsi_pipeline_runs r ON r.id=o.run_id WHERE o.issue_id=i.id ORDER BY r.created_ms DESC LIMIT 1) AS latest_run_id FROM rsi_pipeline_issues i WHERE i.owner=? ORDER BY i.updated_ms DESC LIMIT 100",
                    (owner,),
                )
            ]
        return runs, issues

    def history(self, owner, current, run_id):
        with self.ledger.connection() as db:
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
        return rows, issue_rows, observations, complete
