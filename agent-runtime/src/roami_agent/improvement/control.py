"""Owner control plane: opt-in budgets, machine profiles and leased evaluation requests."""

import json
import secrets
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from roami_agent.improvement.contracts import digest, identifier, load_suite, require
from roami_agent.improvement.daily_suite import daily_coverage
from roami_agent.improvement.policy import validate_policy
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms

DEFAULTS = {
    "enabled": False,
    "timezone": "Asia/Shanghai",
    "hour": 3,
    "daily_tokens": 0,
    "daily_episodes": 120,
    "cases_per_day": 60,
    "suite_id": "",
    "machine_ids": [],
    "auto_candidates": False,
    "candidate_policy": {},
}


class ImprovementControl:
    def __init__(self, ledger):
        self.ledger = ledger

    def preferences(self, owner):
        with self.ledger.connection() as db:
            value = db.execute("SELECT * FROM rsi_preferences WHERE owner=?", (owner,)).fetchone()
            return {
                "revision": value["revision"] if value else 0,
                **DEFAULTS,
                **(json.loads(value["value_json"]) if value else {}),
                "cases_per_day": 60,
            }

    def save(self, owner, raw):
        require(
            isinstance(raw, dict) and {"revision"} <= set(raw) <= {*DEFAULTS, "revision"},
            "RSI_INVALID_SETTINGS",
        )
        prior_values = self.preferences(owner)
        value = {k: raw.get(k, prior_values[k]) for k in DEFAULTS}
        validate_policy(value["candidate_policy"])
        require(type(value["enabled"]) is bool and type(value["auto_candidates"]) is bool)
        require(type(value["hour"]) is int and 0 <= value["hour"] <= 23)
        require(type(value["daily_tokens"]) is int and 0 <= value["daily_tokens"] <= 100_000_000)
        require(type(value["daily_episodes"]) is int and 0 <= value["daily_episodes"] <= 10000)
        require(
            type(value["cases_per_day"]) is int and value["cases_per_day"] == 60,
            "RSI_FULL_SUITE_REQUIRED",
        )
        require(isinstance(value["machine_ids"], list) and len(value["machine_ids"]) <= 32)
        require(len(set(value["machine_ids"])) == len(value["machine_ids"]))
        require(isinstance(value["timezone"], str) and len(value["timezone"]) < 100)
        try:
            ZoneInfo(value["timezone"])
        except (KeyError, ValueError):
            raise DomainError("RSI_INVALID_TIMEZONE") from None
        require(isinstance(value["suite_id"], str))
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT revision FROM rsi_preferences WHERE owner=?", (owner,)
            ).fetchone()
            revision = old[0] if old else 0
            require(
                type(raw["revision"]) is int and raw["revision"] == revision,
                "RSI_SETTINGS_CONFLICT",
            )
            if value["enabled"]:
                require(
                    bool(value["machine_ids"]) and bool(value["suite_id"]), "RSI_SETUP_REQUIRED"
                )
                require(
                    db.execute(
                        "SELECT 1 FROM rsi_suites WHERE owner=? AND id=?",
                        (owner, value["suite_id"]),
                    ).fetchone(),
                    "RSI_SUITE_NOT_FOUND",
                )
                summary = db.execute(
                    "SELECT summary_json FROM rsi_suites WHERE owner=? AND id=?",
                    (owner, value["suite_id"]),
                ).fetchone()
                summary = json.loads(summary[0])
                require(
                    summary.get("daily_coverage", {}).get("complete") is True,
                    "RSI_FORMAL_SUITE_INCOMPLETE",
                )
            for machine in value["machine_ids"]:
                identifier(machine)
                require(
                    db.execute(
                        "SELECT 1 FROM rsi_machines WHERE owner=? AND id=?", (owner, machine)
                    ).fetchone(),
                    "RSI_MACHINE_NOT_FOUND",
                )
            db.execute(
                "INSERT INTO rsi_preferences VALUES(?,?,?,?) ON CONFLICT(owner) DO UPDATE SET revision=excluded.revision,value_json=excluded.value_json,updated_ms=excluded.updated_ms",
                (owner, revision + 1, json.dumps(value), now_ms()),
            )
            db.execute("COMMIT")
        return {"revision": revision + 1, **value}

    def register_machine(self, owner, raw, *, local_only=False):
        require(isinstance(raw, dict))
        machine_id = identifier(raw.get("id"))
        require(raw.get("mode") in {"native_files", "container", "external"}, "RSI_MACHINE_MODE")
        require(isinstance(raw.get("label"), str) and 0 < len(raw["label"]) <= 100)
        if "cache_mode" in raw:
            require(raw["cache_mode"] in {"cold", "warm", "uncontrolled"}, "RSI_INVALID_CACHE_MODE")
            if raw["cache_mode"] != "uncontrolled":
                require(
                    isinstance(raw.get("cache_attestation"), str)
                    and 1 <= len(raw["cache_attestation"]) <= 1000,
                    "RSI_CACHE_ATTESTATION_REQUIRED",
                )
        if local_only:
            require(
                set(raw) <= {"id", "label", "mode"}
                and raw["mode"] in {"native_files", "container"},
                "RSI_MACHINE_MODE",
            )
        if raw["mode"] == "external":
            require(
                isinstance(raw.get("argv"), list) and raw["argv"] and raw["argv"][0].startswith("/")
            )
            require(
                isinstance(raw.get("environment_hash"), str) and len(raw["environment_hash"]) == 64
            )
            require(isinstance(raw.get("model_hash"), str) and len(raw["model_hash"]) == 64)
        with self.ledger.connection() as db:
            busy = db.execute(
                "SELECT 1 FROM rsi_requests WHERE owner=? AND machine_id=? AND state='running'",
                (owner, machine_id),
            ).fetchone()
            require(not busy, "RSI_MACHINE_BUSY")
            db.execute(
                "INSERT INTO rsi_machines VALUES(?,?,?,?) ON CONFLICT(owner,id) DO UPDATE SET profile_json=excluded.profile_json,registered_ms=excluded.registered_ms",
                (owner, machine_id, json.dumps(raw), now_ms()),
            )
        return {k: raw[k] for k in ("id", "label", "mode")}

    def register_suite(self, owner, path):
        suite = load_suite(path)
        summary = {
            "id": suite["id"],
            "count": len(suite["cases"]),
            "layers": dict(Counter(c["layer"] for c in suite["cases"])),
            "splits": dict(Counter(c["split"] for c in suite["cases"])),
            "content_hash": suite["content_hash"],
            "daily_coverage": daily_coverage(suite),
        }
        with self.ledger.connection() as db:
            db.execute(
                "INSERT INTO rsi_suites VALUES(?,?,?,?,?,?) ON CONFLICT(owner,id) DO UPDATE SET path=excluded.path,content_hash=excluded.content_hash,summary_json=excluded.summary_json,registered_ms=excluded.registered_ms",
                (
                    owner,
                    suite["id"],
                    str(path.resolve()),
                    suite["content_hash"],
                    json.dumps(summary),
                    now_ms(),
                ),
            )
        return summary

    def catalog(self, owner):
        with self.ledger.connection() as db:
            machines = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT profile_json FROM rsi_machines WHERE owner=? ORDER BY id", (owner,)
                )
            ]
            suites = [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT summary_json FROM rsi_suites WHERE owner=? ORDER BY id", (owner,)
                )
            ]
            return {
                "machines": [{k: m[k] for k in ("id", "label", "mode")} for m in machines],
                "suites": suites,
            }

    def enqueue(self, owner, *, machine_id, request_key, kind="manual"):
        identifier(machine_id)
        identifier(request_key)
        require(kind in {"manual", "daily"})
        prefs = self.preferences(owner)
        require(
            machine_id in prefs["machine_ids"] and bool(prefs["suite_id"]), "RSI_SETUP_REQUIRED"
        )
        request_id = digest([owner, machine_id, request_key, kind])
        with self.ledger.connection() as db:
            machine = db.execute(
                "SELECT profile_json FROM rsi_machines WHERE owner=? AND id=?", (owner, machine_id)
            ).fetchone()
            suite = db.execute(
                "SELECT path,content_hash FROM rsi_suites WHERE owner=? AND id=?",
                (owner, prefs["suite_id"]),
            ).fetchone()
            require(machine and suite, "RSI_SETUP_REQUIRED")
            payload = {
                "period_key": request_key,
                "preferences": prefs,
                "machine": json.loads(machine[0]),
                "suite": dict(suite),
            }
            db.execute(
                "INSERT OR IGNORE INTO rsi_requests VALUES(?,?,?,?, 'queued',?,?,NULL,NULL,NULL,?)",
                (request_id, owner, machine_id, kind, now_ms(), now_ms(), json.dumps(payload)),
            )
            from roami_agent.improvement.run_records import DEFAULTS as PIPELINE_DEFAULTS
            from roami_agent.improvement.run_records import RunRecords
            from roami_agent.improvement.workflow import DEFAULTS as RESEARCH_DEFAULTS

            pipeline = db.execute(
                "SELECT value_json FROM rsi_pipeline_settings WHERE owner=?", (owner,)
            ).fetchone()
            research = db.execute(
                "SELECT config_json FROM rsi_research_settings WHERE owner=?", (owner,)
            ).fetchone()
            snapshot = {
                "pipeline": {**PIPELINE_DEFAULTS, **(json.loads(pipeline[0]) if pipeline else {})},
                "research": {**RESEARCH_DEFAULTS, **(json.loads(research[0]) if research else {})},
                "preferences": prefs,
                "machine_id": machine_id,
                "suite_hash": suite["content_hash"],
                "case_ids": [],
                "formal_daily": False,
            }
            RunRecords.create_tx(db, owner, request_id, request_id, kind, snapshot)
        return {"id": request_id, "state": "queued"}

    def schedule(self):
        with self.ledger.connection() as db:
            owners = [
                r[0]
                for r in db.execute(
                    "SELECT owner FROM rsi_preferences WHERE json_extract(value_json,'$.enabled')=1"
                )
            ]
        for owner in owners:
            prefs = self.preferences(owner)
            now = datetime.now(ZoneInfo(prefs["timezone"]))
            with self.ledger.connection() as db:
                for request in db.execute(
                    "SELECT id,created_ms,payload_json FROM rsi_requests WHERE owner=? AND kind='daily' AND state='queued'",
                    (owner,),
                ).fetchall():
                    payload = json.loads(request["payload_json"])
                    period = (
                        payload.get("period_key")
                        or datetime.fromtimestamp(
                            request["created_ms"] / 1000, ZoneInfo(prefs["timezone"])
                        )
                        .date()
                        .isoformat()
                    )
                    if period < now.date().isoformat():
                        db.execute(
                            "UPDATE rsi_requests SET state='interrupted',error_code='RSI_SCHEDULE_EXPIRED',updated_ms=? WHERE id=? AND state='queued'",
                            (now_ms(), request["id"]),
                        )
            if now.hour >= prefs["hour"]:
                for machine in prefs["machine_ids"]:
                    self.enqueue(
                        owner, machine_id=machine, request_key=now.date().isoformat(), kind="daily"
                    )

    def claim(self):
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            request = db.execute(
                "SELECT r.* FROM rsi_requests r WHERE r.state='queued' AND (r.kind='manual' OR EXISTS(SELECT 1 FROM rsi_preferences p WHERE p.owner=r.owner AND json_extract(p.value_json,'$.enabled')=1)) ORDER BY r.created_ms,r.id LIMIT 1"
            ).fetchone()
            if not request:
                return None
            token = secrets.token_hex(16)
            db.execute(
                "UPDATE rsi_requests SET state='running',claim=?,updated_ms=? WHERE id=?",
                (token, now_ms(), request["id"]),
            )
            db.execute("COMMIT")
            return {**dict(request), "claim": token}

    def profiles(self, request):
        payload = json.loads(request["payload_json"])
        prefs = {
            **payload["preferences"],
            "cases_per_day": 60,
            "period_key": payload.get("period_key", request["id"]),
        }
        return prefs, payload["machine"], payload["suite"]

    def finish(self, request, state, *, cycle_id=None, error_code=None):
        require(state in {"completed", "blocked", "interrupted"})
        with self.ledger.connection() as db:
            changed = db.execute(
                "UPDATE rsi_requests SET state=?,updated_ms=?,cycle_id=?,error_code=? WHERE id=? AND owner=? AND claim=? AND state IN ('running','cancelling')",
                (
                    state,
                    now_ms(),
                    cycle_id,
                    error_code,
                    request["id"],
                    request["owner"],
                    request["claim"],
                ),
            )
            require(changed.rowcount == 1, "RSI_REQUEST_LEASE_LOST")

    def requests(self, owner):
        with self.ledger.connection() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,machine_id,kind,state,created_ms,updated_ms,cycle_id,error_code FROM rsi_requests WHERE owner=? ORDER BY created_ms DESC LIMIT 30",
                    (owner,),
                )
            ]

    def recover(self):
        with self.ledger.connection() as db:
            return db.execute(
                "UPDATE rsi_requests SET state='interrupted',error_code='RSI_WORKER_RESTARTED',updated_ms=? WHERE state IN ('running','cancelling')",
                (now_ms(),),
            ).rowcount

    def cancel(self, owner, request_id):
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            request = db.execute(
                "SELECT state FROM rsi_requests WHERE owner=? AND id=?", (owner, request_id)
            ).fetchone()
            if not request:
                raise DomainError("RSI_REQUEST_NOT_FOUND", 404)
            state = (
                "interrupted"
                if request[0] == "queued"
                else "cancelling"
                if request[0] == "running"
                else request[0]
            )
            db.execute(
                "UPDATE rsi_requests SET state=?,updated_ms=? WHERE owner=? AND id=?",
                (state, now_ms(), owner, request_id),
            )
            if state == "interrupted":
                db.execute(
                    "UPDATE rsi_pipeline_runs SET state='cancelled',updated_ms=? WHERE owner=? AND id=? AND state='queued'",
                    (now_ms(), owner, request_id),
                )
                db.execute(
                    "UPDATE rsi_pipeline_nodes SET state='skipped',error_code='RSI_CANCELLED',finished_ms=? WHERE run_id IN (SELECT id FROM rsi_pipeline_runs WHERE id=? AND owner=? AND state='cancelled') AND state='pending'",
                    (now_ms(), request_id, owner),
                )
            return {"id": request_id, "state": state}
