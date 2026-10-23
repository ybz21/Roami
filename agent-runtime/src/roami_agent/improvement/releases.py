"""Recomputed release evidence, immutable conversation bindings and reversible admissions."""

import json

from roami_agent.improvement.comparison import compare
from roami_agent.improvement.contracts import digest, identifier, require
from roami_agent.improvement.policy import validate_policy
from roami_agent.protocol.errors import DomainError
from roami_agent.protocol.identity import now_ms


class Releases:
    def __init__(self, ledger):
        self.ledger = ledger

    def evidence(self, owner, cycle_ids):
        require(isinstance(cycle_ids, list) and 1 <= len(cycle_ids) <= 100)
        require(len(cycle_ids) == len(set(cycle_ids)))
        cycles = [self.ledger.get(owner, identifier(i)) for i in cycle_ids]
        require(all(c["state"] == "completed" for c in cycles), "RSI_EVIDENCE_INCOMPLETE")
        for cycle in cycles:
            if cycle["manifest"].get("review_required"):
                expected = set(cycle["manifest"]["case_ids"])
                require(
                    len(cycle["trials"]) == 2 * len(expected)
                    and all(t.get("log_review", {}).get("complete") for t in cycle["trials"])
                    and all(
                        {t["case_id"] for t in cycle["trials"] if t["arm"] == arm} == expected
                        for arm in ("baseline", "candidate")
                    ),
                    "RSI_REVIEW_INCOMPLETE",
                )
        first = cycles[0]["manifest"]
        require(first["baseline_id"] != first["candidate_id"], "RSI_PROMOTION_REJECTED")
        for cycle in cycles:
            manifest = cycle["manifest"]
            for key in ("baseline_id", "candidate_id", "implementation_hash", "standard_version"):
                require(
                    manifest.get(key) == first.get(key) and first.get(key), "RSI_EVIDENCE_MISMATCH"
                )
        arms = {arm: [] for arm in ("baseline", "candidate")}
        for repetition, cycle in enumerate(cycles):
            for t in cycle["trials"]:
                require(t["arm"] in arms)
                require(
                    t.get("policy_id") == cycle["manifest"][t["arm"] + "_id"],
                    "RSI_EVIDENCE_MISMATCH",
                )
                arms[t["arm"]].append({**t, "repetition": repetition})
        comparison = compare(arms["baseline"], arms["candidate"])
        return {
            "cycle_ids": cycle_ids,
            "comparison": comparison,
            "policy": validate_policy(first["candidate_policy"]),
            "candidate_id": first["candidate_id"],
            "implementation_hash": first["implementation_hash"],
            "evidence_hash": digest([c["manifest"] for c in cycles] + [arms]),
        }

    def publish(self, owner, cycle_ids, *, expected_seq, request_key):
        identifier(request_key)
        evidence = self.evidence(owner, cycle_ids)
        require(evidence["comparison"]["eligible_for_promotion"], "RSI_PROMOTION_REJECTED")
        release_id = digest([owner, evidence["evidence_hash"], evidence["candidate_id"]])
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM rsi_release_events WHERE owner=? AND request_key=?",
                (owner, request_key),
            ).fetchone()
            if existing:
                require(
                    existing["release_id"] == release_id and existing["action"] == "activate",
                    "RSI_REQUEST_KEY_CONFLICT",
                )
                return dict(existing)
            active = (
                db.execute(
                    "SELECT MAX(seq) FROM rsi_release_events WHERE owner=?", (owner,)
                ).fetchone()[0]
                or 0
            )
            require(
                type(expected_seq) is int and expected_seq == active,
                "RSI_RELEASE_REVISION_CONFLICT",
            )
            timestamp = now_ms()
            policy = json.dumps(evidence["policy"], sort_keys=True)
            db.execute(
                "INSERT OR IGNORE INTO rsi_releases VALUES(?,?,?,?,?)",
                (release_id, owner, policy, json.dumps(evidence), timestamp),
            )
            event = db.execute(
                "INSERT INTO rsi_release_events(owner,release_id,action,policy_json,created_ms,request_key) VALUES(?,?,'activate',?,?,?)",
                (owner, release_id, policy, timestamp, request_key),
            ).lastrowid
            db.execute("COMMIT")
            return {
                "seq": event,
                "release_id": release_id,
                "action": "activate",
                "created_ms": timestamp,
            }

    def rollback(self, owner, *, expected_seq, request_key, release_id=None):
        identifier(request_key)
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM rsi_release_events WHERE owner=? AND request_key=?",
                (owner, request_key),
            ).fetchone()
            if existing:
                require(
                    existing["action"] == "rollback" and existing["release_id"] == release_id,
                    "RSI_REQUEST_KEY_CONFLICT",
                )
                return dict(existing)
            active = (
                db.execute(
                    "SELECT MAX(seq) FROM rsi_release_events WHERE owner=?", (owner,)
                ).fetchone()[0]
                or 0
            )
            require(
                type(expected_seq) is int and expected_seq == active,
                "RSI_RELEASE_REVISION_CONFLICT",
            )
            policy = "{}"
            if release_id:
                release = db.execute(
                    "SELECT policy_json FROM rsi_releases WHERE owner=? AND id=?",
                    (owner, release_id),
                ).fetchone()
                if not release:
                    raise DomainError("RSI_RELEASE_NOT_FOUND", 404)
                policy = release[0]
            timestamp = now_ms()
            event = db.execute(
                "INSERT INTO rsi_release_events(owner,release_id,action,policy_json,created_ms,request_key) VALUES(?,?,'rollback',?,?,?)",
                (owner, release_id, policy, timestamp, request_key),
            ).lastrowid
            db.execute("COMMIT")
            return {
                "seq": event,
                "release_id": release_id,
                "action": "rollback",
                "created_ms": timestamp,
            }

    def list(self, owner):
        if not self.ledger.path.exists():
            return {"seq": 0, "active": None, "history": []}
        with self.ledger.connection() as db:
            events = [
                dict(r)
                for r in db.execute(
                    "SELECT seq,release_id,action,created_ms FROM rsi_release_events WHERE owner=? ORDER BY seq DESC LIMIT 50",
                    (owner,),
                )
            ]
            return {
                "seq": events[0]["seq"] if events else 0,
                "active": events[0]["release_id"] if events else None,
                "history": events,
            }

    def bind(self, owner, conversation_id, created_ms, baseline):
        if not self.ledger.path.exists():
            return None
        with self.ledger.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            binding = db.execute(
                "SELECT * FROM rsi_bindings WHERE owner=? AND conversation_id=?",
                (owner, conversation_id),
            ).fetchone()
            if binding:
                return {
                    "release_id": binding["release_id"],
                    "event_seq": binding["event_seq"],
                    "policy": json.loads(binding["policy_json"]),
                }
            selected = db.execute(
                "SELECT * FROM rsi_release_events WHERE owner=? AND created_ms<? ORDER BY seq DESC LIMIT 1",
                (owner, created_ms),
            ).fetchone()
            policy = {**baseline, **json.loads(selected["policy_json"])} if selected else baseline
            release_id = selected["release_id"] if selected else None
            event_seq = selected["seq"] if selected else None
            db.execute(
                "INSERT INTO rsi_bindings VALUES(?,?,?,?,?,?)",
                (owner, conversation_id, release_id, event_seq, json.dumps(policy), created_ms),
            )
            db.execute("COMMIT")
            return {"release_id": release_id, "event_seq": event_seq, "policy": policy}
