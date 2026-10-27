"""Private experiment ledger with atomic daily admission and no replay on restart."""

import fcntl
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from roami_agent.improvement.contracts import digest, require
from roami_agent.improvement.spending_policy import uses_shared_model_limit
from roami_agent.protocol.errors import DomainError

SCHEMA = """
CREATE TABLE IF NOT EXISTS rsi_schema (version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS rsi_budgets (
 owner TEXT NOT NULL, day TEXT NOT NULL, tokens_limit INTEGER NOT NULL,
 episodes_limit INTEGER NOT NULL, tokens_reserved INTEGER NOT NULL DEFAULT 0,
 episodes_reserved INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(owner,day)
);
CREATE TABLE IF NOT EXISTS rsi_cycles (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, day TEXT NOT NULL,
 state TEXT NOT NULL, started_ms INTEGER NOT NULL, finished_ms INTEGER,
 heartbeat_ms INTEGER NOT NULL, manifest_json TEXT NOT NULL, report_json TEXT
);
CREATE INDEX IF NOT EXISTS rsi_cycles_owner ON rsi_cycles(owner,started_ms DESC);
CREATE TABLE IF NOT EXISTS rsi_trials (
 cycle_id TEXT NOT NULL REFERENCES rsi_cycles(id), arm TEXT NOT NULL,
 case_id TEXT NOT NULL, repetition INTEGER NOT NULL, record_json TEXT NOT NULL,
 PRIMARY KEY(cycle_id,arm,case_id,repetition)
);
CREATE TABLE IF NOT EXISTS rsi_preferences (
 owner TEXT PRIMARY KEY, revision INTEGER NOT NULL, value_json TEXT NOT NULL, updated_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS rsi_machines (
 owner TEXT NOT NULL, id TEXT NOT NULL, profile_json TEXT NOT NULL, registered_ms INTEGER NOT NULL,
 PRIMARY KEY(owner,id)
);
CREATE TABLE IF NOT EXISTS rsi_suites (
 owner TEXT NOT NULL, id TEXT NOT NULL, path TEXT NOT NULL, content_hash TEXT NOT NULL,
 summary_json TEXT NOT NULL, registered_ms INTEGER NOT NULL, PRIMARY KEY(owner,id)
);
CREATE TABLE IF NOT EXISTS rsi_requests (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, machine_id TEXT NOT NULL, kind TEXT NOT NULL,
 state TEXT NOT NULL, created_ms INTEGER NOT NULL, updated_ms INTEGER NOT NULL,
 claim TEXT, cycle_id TEXT, error_code TEXT, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rsi_releases (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, policy_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
 created_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS rsi_release_events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, release_id TEXT,
 action TEXT NOT NULL, policy_json TEXT NOT NULL, created_ms INTEGER NOT NULL,
 request_key TEXT NOT NULL, UNIQUE(owner,request_key)
);
CREATE TABLE IF NOT EXISTS rsi_bindings (
 owner TEXT NOT NULL, conversation_id TEXT NOT NULL, release_id TEXT, event_seq INTEGER,
 policy_json TEXT NOT NULL, created_ms INTEGER NOT NULL, PRIMARY KEY(owner,conversation_id)
);
"""


class Ledger:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        require(not self.path.is_symlink(), "RSI_PRIVATE_LEDGER_REQUIRED")
        lock = os.open(str(self.path) + ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        db = None
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            os.fchmod(fd, 0o600)
            os.close(fd)
            db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            db.row_factory = sqlite3.Row
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='rsi_schema'").fetchone()
            if exists:
                require(
                    [r[0] for r in db.execute("SELECT version FROM rsi_schema")] in ([1], [2], [3]),
                    "RSI_LEDGER_VERSION",
                )
            db.executescript(
                "PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;"
            )
            db.executescript(SCHEMA)
            from roami_agent.improvement.workflow import SCHEMA as RESEARCH_SCHEMA

            db.executescript(RESEARCH_SCHEMA)
            from roami_agent.improvement.run_records import SCHEMA as PIPELINE_SCHEMA

            db.executescript(PIPELINE_SCHEMA)
            db.execute("DELETE FROM rsi_schema WHERE version IN (1,2)")
            db.execute("INSERT OR IGNORE INTO rsi_schema VALUES (3)")
            yield db
            if db.in_transaction:
                db.commit()
        finally:
            if db is not None:
                db.close()
            os.close(lock)

    def reserve(self, owner, day, manifest, *, tokens_limit, episodes_limit):
        shared = uses_shared_model_limit(self)
        require(isinstance(owner, str) and 0 < len(owner) <= 200)
        require(shared or type(tokens_limit) is int and tokens_limit > 0)
        require(shared or type(episodes_limit) is int and 0 < episodes_limit <= 10000)
        cycle_id = digest([owner, day, manifest])
        tokens = manifest["reserved_tokens"]
        episodes = manifest["reserved_episodes"]
        machine_id = manifest.get("machine", {}).get("id")
        require(isinstance(machine_id, str) and bool(machine_id), "RSI_MACHINE_ID_REQUIRED")
        require(type(tokens) is int and tokens >= 0 and type(episodes) is int and episodes > 0)
        timestamp = time.time_ns() // 1_000_000
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT id,state FROM rsi_cycles WHERE owner=? AND day=? AND json_extract(manifest_json,'$.machine.id')=? AND COALESCE(json_extract(manifest_json,'$.request_key'),'daily')=?",
                (owner, day, machine_id, manifest.get("request_key", "daily")),
            ).fetchone()
            if existing:
                return existing["id"], False
            db.execute(
                "INSERT OR IGNORE INTO rsi_budgets(owner,day,tokens_limit,episodes_limit) VALUES(?,?,?,?)",
                (owner, day, tokens_limit, episodes_limit),
            )
            budget = db.execute(
                "SELECT * FROM rsi_budgets WHERE owner=? AND day=?", (owner, day)
            ).fetchone()
            require(
                shared
                or budget["tokens_limit"] == tokens_limit
                and budget["episodes_limit"] == episodes_limit,
                "RSI_DAILY_BUDGET_ALREADY_FROZEN",
            )
            require(
                shared
                or budget["tokens_reserved"] + tokens <= tokens_limit
                and budget["episodes_reserved"] + episodes <= episodes_limit,
                "RSI_DAILY_BUDGET",
            )
            db.execute(
                "UPDATE rsi_budgets SET tokens_reserved=tokens_reserved+?,episodes_reserved=episodes_reserved+? WHERE owner=? AND day=?",
                (tokens, episodes, owner, day),
            )
            db.execute(
                "INSERT INTO rsi_cycles VALUES(?,?,?,'running',?,NULL,?,?,NULL)",
                (cycle_id, owner, day, timestamp, timestamp, json.dumps(manifest)),
            )
            db.execute("COMMIT")
        return cycle_id, True

    def append(self, owner, cycle_id, arm, trial):
        require(arm in {"baseline", "candidate"})
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            cycle = db.execute(
                "SELECT state FROM rsi_cycles WHERE id=? AND owner=?", (cycle_id, owner)
            ).fetchone()
            require(cycle is not None and cycle["state"] == "running", "RSI_CYCLE_NOT_RUNNING")
            db.execute(
                "INSERT INTO rsi_trials VALUES(?,?,?,?,?)",
                (
                    cycle_id,
                    arm,
                    trial["case_id"],
                    trial.get("repetition", 0),
                    json.dumps(trial, allow_nan=False),
                ),
            )
            db.execute(
                "UPDATE rsi_cycles SET heartbeat_ms=? WHERE id=?",
                (time.time_ns() // 1_000_000, cycle_id),
            )
            db.execute("COMMIT")

    def finish(self, owner, cycle_id, report, *, state="completed"):
        require(state in {"completed", "failed", "interrupted"})
        with self.connection() as db:
            changed = db.execute(
                "UPDATE rsi_cycles SET state=?,finished_ms=?,report_json=? WHERE id=? AND owner=? AND state='running'",
                (
                    state,
                    time.time_ns() // 1_000_000,
                    json.dumps(report, allow_nan=False),
                    cycle_id,
                    owner,
                ),
            )
            require(changed.rowcount == 1, "RSI_CYCLE_NOT_RUNNING")

    def recover(self, owner, *, stale_seconds=3600):
        """Unknown in-flight usage keeps its reservation; restarting does not retry work."""
        require(type(stale_seconds) is int and stale_seconds >= 60)
        timestamp = time.time_ns() // 1_000_000
        with self.connection() as db:
            changed = db.execute(
                "UPDATE rsi_cycles SET state='interrupted',finished_ms=?,report_json=? WHERE owner=? AND state='running' AND heartbeat_ms<?",
                (
                    timestamp,
                    json.dumps({"reason": "worker_lost", "usage_known": False}),
                    owner,
                    timestamp - stale_seconds * 1000,
                ),
            )
            return changed.rowcount

    def list(self, owner, limit=20):
        require(type(limit) is int and 1 <= limit <= 100)
        if not self.path.exists():
            return []
        with self.connection() as db:
            return [
                {
                    "id": r["id"],
                    "day": r["day"],
                    "state": r["state"],
                    "started_ms": r["started_ms"],
                    "finished_ms": r["finished_ms"],
                    "report": json.loads(r["report_json"]) if r["report_json"] else None,
                    "machine_id": json.loads(r["manifest_json"])["machine"]["id"],
                }
                for r in db.execute(
                    "SELECT * FROM rsi_cycles WHERE owner=? ORDER BY started_ms DESC LIMIT ?",
                    (owner, limit),
                )
            ]

    def get(self, owner, cycle_id):
        with self.connection() as db:
            result = db.execute(
                "SELECT * FROM rsi_cycles WHERE owner=? AND id=?", (owner, cycle_id)
            ).fetchone()
            if result is None:
                raise DomainError("RSI_CYCLE_NOT_FOUND", 404)
            return {
                "id": result["id"],
                "state": result["state"],
                "day": result["day"],
                "manifest": json.loads(result["manifest_json"]),
                "report": json.loads(result["report_json"]) if result["report_json"] else None,
                "trials": [
                    {"arm": r["arm"], **json.loads(r["record_json"])}
                    for r in db.execute(
                        "SELECT * FROM rsi_trials WHERE cycle_id=? ORDER BY case_id,arm,repetition",
                        (cycle_id,),
                    )
                ],
            }
