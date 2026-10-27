"""Owner-scoped runs, node attempts, artifacts and repeatable issue observations."""

import hashlib
import json
import os
import re
import secrets
from pathlib import Path

from roami_agent.improvement.case_catalog import case_identity
from roami_agent.improvement.contracts import digest, require
from roami_agent.improvement.spending_policy import uses_shared_model_limit
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms

STAGES = ("evaluate", "review", "issue", "repair", "verify", "publish", "observe")
DEFAULTS = {
    "revision": 0,
    "auto_publish": False,
    "daily_tokens": 1000000,
    "generation_tokens": 300000,
    "codex_tokens": 64000,
    "output_tokens": 8192,
    "main_output_tokens": None,
    "worker_output_tokens": None,
    "memory_output_tokens": 2048,
    "main_model": None,
    "main_reasoning_effort": None,
    "worker_model": None,
    "worker_reasoning_effort": None,
    "memory_model": None,
    "memory_reasoning_effort": None,
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS rsi_pipeline_settings(owner TEXT PRIMARY KEY, value_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rsi_pipeline_runs(
 id TEXT PRIMARY KEY,owner TEXT NOT NULL,request_key TEXT NOT NULL,mode TEXT NOT NULL,state TEXT NOT NULL,
 created_ms INTEGER NOT NULL,updated_ms INTEGER NOT NULL,snapshot_json TEXT NOT NULL,summary_json TEXT,
 cycle_id TEXT,issue_json TEXT,lease TEXT,expires_ms INTEGER,UNIQUE(owner,request_key)
);
CREATE TABLE IF NOT EXISTS rsi_pipeline_nodes(
 run_id TEXT NOT NULL,node TEXT NOT NULL,attempt INTEGER NOT NULL,state TEXT NOT NULL,
 config_json TEXT NOT NULL,started_ms INTEGER,finished_ms INTEGER,error_code TEXT,
 PRIMARY KEY(run_id,node,attempt)
);
CREATE TABLE IF NOT EXISTS rsi_pipeline_cases(
 run_id TEXT NOT NULL,case_id TEXT NOT NULL,source_hash TEXT NOT NULL,result_json TEXT NOT NULL,
 PRIMARY KEY(run_id,case_id)
);
CREATE TABLE IF NOT EXISTS rsi_pipeline_issues(
 id TEXT PRIMARY KEY,owner TEXT NOT NULL,case_id TEXT NOT NULL,code TEXT NOT NULL,
 created_ms INTEGER NOT NULL,updated_ms INTEGER NOT NULL,UNIQUE(owner,case_id,code)
);
CREATE TABLE IF NOT EXISTS rsi_pipeline_observations(
 run_id TEXT NOT NULL,issue_id TEXT NOT NULL,status TEXT NOT NULL,evidence_json TEXT NOT NULL,
 PRIMARY KEY(run_id,issue_id)
);
CREATE TABLE IF NOT EXISTS rsi_pipeline_artifacts(
 id TEXT PRIMARY KEY,run_id TEXT NOT NULL,node TEXT NOT NULL,name TEXT NOT NULL,path TEXT NOT NULL,
 sha256 TEXT NOT NULL,bytes INTEGER NOT NULL,UNIQUE(run_id,node,name)
);
CREATE TABLE IF NOT EXISTS rsi_pipeline_events(
 seq INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL,node TEXT NOT NULL,state TEXT NOT NULL,
 detail TEXT,created_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS rsi_pipeline_costs(
 id TEXT PRIMARY KEY,owner TEXT NOT NULL,run_id TEXT NOT NULL,reserved INTEGER NOT NULL,
 state TEXT NOT NULL,result_json TEXT
);
CREATE INDEX IF NOT EXISTS rsi_pipeline_observation_issue ON rsi_pipeline_observations(issue_id);
CREATE INDEX IF NOT EXISTS rsi_pipeline_run_owner ON rsi_pipeline_runs(owner,created_ms);
CREATE TABLE IF NOT EXISTS rsi_pipeline_effects(
 run_id TEXT PRIMARY KEY,state TEXT NOT NULL,receipt_json TEXT
);
"""


def code(value):
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", value)
        else "UNKNOWN"
    )


def trial_summary(case, result, root=None):
    grade, metrics = result.get("grade", {}), result.get("metrics", {})
    signals = (
        {code(result.get("execution_error") or grade.get("reason"))}
        if not grade.get("passed")
        else set()
    )
    signals -= {"UNKNOWN", "assertions_passed"}
    checks = {code(k): v for k, v in grade.get("checks", {}).items() if type(v) is bool}
    signals.update("check:" + k for k, v in checks.items() if not v)
    tools, roles, files = [], {}, []
    execution_log_found = False
    if root:
        root = Path(root)
        for name in ("state/execution-log.json", "execution-log.json"):
            path = root / name
            if not path.is_file():
                continue
            data = json.loads(path.read_text())
            execution_log_found = True
            for item in data.get("tool_calls", []):
                error = None
                if item.get("state") == "failed":
                    try:
                        output = item.get("result_json", {})
                        output = json.loads(output) if isinstance(output, str) else output
                        output = json.loads(output.get("text", "{}"))
                        error = code(output.get("error"))
                    except (TypeError, ValueError):
                        error = "TOOL_FAILED"
                    signals.add(error)
                tools.append(
                    {
                        "name": code(item.get("tool_name")),
                        "state": item.get("state"),
                        "error": error,
                    }
                )
            break
        model = root / "model-log.json"
        if model.is_file():
            for item in json.loads(model.read_text()).get("requests", []):
                role = code(item.get("role"))
                usage = item.get("measurement") or {}
                row = roles.setdefault(
                    role, {"calls": 0, "known_input": 0, "known_output": 0, "unknown": 0}
                )
                row["calls"] += 1
                if type(usage.get("inputTokens")) is int and type(usage.get("outputTokens")) is int:
                    row["known_input"] += usage["inputTokens"]
                    row["known_output"] += usage["outputTokens"]
                else:
                    row["unknown"] += 1
                if item.get("error_code"):
                    signals.add(code(item["error_code"]))
        files = [
            str(p.relative_to(root / "workspace"))
            for p in (root / "workspace").rglob("*")
            if p.is_file()
            and p.suffix in {".py", ".md", ".html", ".json", ".csv", ".svg", ".pptx"}
            and "__pycache__" not in p.parts
        ][:32]
    blocked = bool(
        signals
        & {
            "RSI_TOKEN_BUDGET",
            "RSI_DAILY_BUDGET",
            "RSI_REQUEST_BUDGET",
            "UPSTREAM_USAGE_UNKNOWN",
            "RSI_USAGE_UNKNOWN",
            "MODEL_PROXY_DAILY_LIMIT",
            "MODEL_PROXY_USAGE_UNKNOWN",
            "MODEL_PROXY_CURRENCY_MISMATCH",
        }
    )
    state = (
        "blocked"
        if blocked
        else "pending_score"
        if grade.get("pending")
        else "passed"
        if grade.get("passed")
        else "failed"
    )
    identity = case_identity(case)
    return {
        "case_id": case["id"],
        "name": identity["name"],
        "description": identity["description"],
        "category": case.get("category", ""),
        "kind": "mechanism"
        if case.get("layer") == "mechanism" or case.get("judge", {}).get("kind") == "mechanism"
        else "task",
        "source_hash": digest(case),
        "state": state,
        "passed": grade.get("passed") is True,
        "hard_passed": grade.get("hard_passed") is True,
        "pending": grade.get("pending") is True,
        "quality": grade.get("quality"),
        "checks": checks,
        "signals": sorted(signals),
        "metrics": {
            k: metrics.get(k)
            for k in ("tokens", "token_coverage", "model_calls", "elapsed_ms", "model_ms")
        },
        "tools": tools,
        "tool_calls": len(tools) if execution_log_found else metrics.get("tool_calls"),
        "roles": roles,
        "files": files,
    }


class RunRecords:
    def __init__(self, ledger):
        self.ledger = ledger
        self.root = ledger.path.parent / "pipeline-artifacts"

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

    def directory(self, owner, run_id):
        require(
            isinstance(run_id, str) and re.fullmatch(r"[a-f0-9]{64}", run_id), "RSI_RUN_NOT_FOUND"
        )
        path = self.root / digest(owner)[:24] / run_id
        require(not path.is_symlink(), "RSI_PRIVATE_OUTPUT_REQUIRED")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

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

    def artifact(self, owner, run_id, node, name, value):
        require(
            node in STAGES and re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", name), "RSI_INVALID_ARTIFACT"
        )
        self.get(owner, run_id)
        directory = self.directory(owner, run_id) / node
        directory.mkdir(mode=0o700, exist_ok=True)
        require(not directory.is_symlink(), "RSI_PRIVATE_OUTPUT_REQUIRED")
        path = directory / name
        raw = (
            value.encode()
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, indent=2).encode()
        )
        require(len(raw) <= 4000000, "RSI_PAYLOAD_TOO_LARGE")
        sha = hashlib.sha256(raw).hexdigest()
        with self.ledger.connection() as db:
            existing = db.execute(
                "SELECT sha256 FROM rsi_pipeline_artifacts WHERE run_id=? AND node=? AND name=?",
                (run_id, node, name),
            ).fetchone()
            if existing:
                require(existing[0] == sha, "RSI_ARTIFACT_CHANGED")
                return
        temp = path.with_suffix(path.suffix + ".tmp")
        with temp.open("xb") as output:
            output.write(raw)
        temp.chmod(0o600)
        with temp.open("rb") as file:
            os.fsync(file.fileno())
        temp.replace(path)
        with self.ledger.connection() as db:
            require(
                db.execute(
                    "SELECT 1 FROM rsi_pipeline_runs WHERE id=? AND owner=?", (run_id, owner)
                ).fetchone(),
                "RSI_RUN_NOT_FOUND",
            )
            db.execute(
                "INSERT OR IGNORE INTO rsi_pipeline_artifacts VALUES(?,?,?,?,?,?,?)",
                (
                    digest([run_id, node, name]),
                    run_id,
                    node,
                    name,
                    node + "/" + name,
                    sha,
                    len(raw),
                ),
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
            for case in cases.values():
                for signal in case["signals"]:
                    if signal == "MODEL_PROXY_DAILY_LIMIT":
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
                if prior is None and (case is None or issue["code"] not in case["signals"]):
                    db.execute(
                        "DELETE FROM rsi_pipeline_observations WHERE run_id=? AND issue_id=?",
                        (run_id, issue["id"]),
                    )
                    continue
                status = (
                    "not_tested"
                    if case is None
                    else "present"
                    if issue["code"] in case["signals"]
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

    def view(self, owner):
        self.sync_research(owner)
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
        from roami_agent.improvement.github_publication import publication_profile

        try:
            publication = publication_profile(self.ledger.path.parent, owner)
        except (DomainError, OSError, ValueError):
            publication = None
        return {
            "settings": {
                key: val
                for key, val in self.settings(owner).items()
                if not uses_shared_model_limit(self.ledger) or key in {"revision", "auto_publish"}
            },
            "runs": runs,
            "issues": issues,
            "publication": {"repository": publication["repository"] if publication else None},
        }

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

    def read_artifact(self, owner, run_id, artifact_id):
        self.get(owner, run_id)
        with self.ledger.connection() as db:
            row = db.execute(
                "SELECT * FROM rsi_pipeline_artifacts WHERE id=? AND run_id=?",
                (artifact_id, run_id),
            ).fetchone()
            require(row is not None, "RSI_ARTIFACT_UNAVAILABLE")
        root = self.directory(owner, run_id)
        path = root / row["path"]
        require(
            not path.is_symlink()
            and path.resolve().is_relative_to(root.resolve())
            and path.stat().st_size <= 4000000,
            "RSI_ARTIFACT_UNAVAILABLE",
        )
        raw = path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == row["sha256"], "RSI_ARTIFACT_CHANGED")
        return {"name": row["name"], "text": raw.decode("utf-8"), "sha256": row["sha256"]}

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

    def begin_request(self, request):
        payload = json.loads(request["payload_json"])
        if payload.get("diagnostic"):
            return
        owner, run_id = request["owner"], request["id"]
        config = self.settings(owner)
        snapshot = {
            "pipeline": config,
            "preferences": payload["preferences"],
            "machine_id": request["machine_id"],
            "suite_hash": payload["suite"]["content_hash"],
            "case_ids": [],
            "formal_daily": True,
        }
        with self.ledger.connection() as db:
            self.create_tx(db, owner, run_id, run_id, request["kind"], snapshot)
        self.node(owner, run_id, "evaluate", "running")
        self.set_state(owner, run_id, "running")

    def freeze_cases(self, owner, run_id, suite):
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
                snapshot["case_definitions"] = {ident: case_identity(cases[ident]) for ident in ids}
            db.execute(
                "UPDATE rsi_pipeline_runs SET snapshot_json=? WHERE owner=? AND id=?",
                (json.dumps(snapshot), owner, run_id),
            )

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

            from roami_agent.improvement.control import DEFAULTS as EVALUATION_DEFAULTS

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

    def capture_request(self, request):
        owner, run_id = request["owner"], request["id"]
        with self.ledger.connection() as db:
            row = db.execute(
                "SELECT * FROM rsi_requests WHERE owner=? AND id=?", (owner, run_id)
            ).fetchone()
        if not row:
            return
        row = dict(row)
        payload = json.loads(row["payload_json"])
        value = self.get(owner, run_id)
        if row["state"] == "interrupted":
            self.node(owner, run_id, "evaluate", "blocked", "RSI_CANCELLED")
            for stage in STAGES[1:]:
                self.node(owner, run_id, stage, "skipped", "RSI_CANCELLED")
            self.observations(owner, run_id)
            self.set_state(owner, run_id, "cancelled")
            return
        if payload.get("diagnostic") and value["state"] != "running":
            return
        if row["cycle_id"]:
            cycle = self.ledger.get(owner, row["cycle_id"])
            with self.ledger.connection() as db:
                db.execute(
                    "UPDATE rsi_pipeline_runs SET cycle_id=? WHERE id=? AND owner=?",
                    (row["cycle_id"], run_id, owner),
                )
            by_case = {}
            for trial in cycle["trials"]:
                if trial["case_id"] not in by_case or trial["arm"] == "candidate":
                    by_case[trial["case_id"]] = trial
            for case_id, trial in by_case.items():
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
                )
                outcome["source_hash"] = trial["case_hash"]
                outcome["arm"] = trial["arm"]
                self.case(owner, run_id, outcome)
            self.observations(owner, run_id)
            report = cycle["report"] or {}
            self.artifact(owner, run_id, "evaluate", "evaluation-report.json", report)
            self.node(
                owner,
                run_id,
                "evaluate",
                "succeeded" if report.get("full_suite_complete") else "blocked",
                row["error_code"],
            )
            summary = {
                "cases": len(by_case),
                "expected_cases": cycle["manifest"].get("expected_cases"),
                "formal": cycle["manifest"].get("formal_daily_suite"),
                "evaluation_complete": report.get("evaluation_complete", False),
            }
            with self.ledger.connection() as db:
                settings = db.execute(
                    "SELECT config_json FROM rsi_research_settings WHERE owner=?", (owner,)
                ).fetchone()
            if (
                report.get("evaluation_complete")
                and settings
                and json.loads(settings[0]).get("enabled")
            ):
                self.set_state(owner, run_id, "awaiting_research", summary)
                return
            self.queue_report(owner, run_id, summary, reserve=True)
        else:
            error = code(row["error_code"])
            self.case(
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
            self.observations(owner, run_id)
            self.node(owner, run_id, "evaluate", "blocked", error)
            self.queue_report(
                owner,
                run_id,
                {
                    "cases": 0,
                    "expected_cases": len(value["snapshot"].get("case_ids", [])) or 60,
                    "error": error,
                },
                reserve=not bool(payload.get("diagnostic")),
            )

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

    def sync_research(self, owner):
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
        for run_id, document in documents:
            try:
                self.artifact(
                    owner,
                    run_id,
                    "review",
                    "formal-review-" + digest(document)[:8] + ".md",
                    document,
                )
            except DomainError:
                pass
        for run_id, stage, receipt in receipts:
            self.artifact(owner, run_id, stage, "action-" + digest(receipt)[:20] + ".json", receipt)
