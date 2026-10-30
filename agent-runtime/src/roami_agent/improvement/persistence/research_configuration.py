"""ResearchConfiguration persistence within the research aggregate."""

import json
from pathlib import Path

from roami_agent.improvement.domain.contracts import require
from roami_agent.improvement.domain.research_configuration import DEFAULTS, LEGACY_FIELDS


class ResearchConfiguration:
    def __init__(self, owner):
        self.owner, self.ledger = owner, owner.ledger

    def settings(self, owner):
        with self.ledger.connection() as db:
            r = db.execute("SELECT * FROM rsi_research_settings WHERE owner=?", (owner,)).fetchone()
            value = {
                **DEFAULTS,
                **{
                    k: v
                    for k, v in (json.loads(r["config_json"]) if r else {}).items()
                    if k in DEFAULTS
                },
                "revision": r["revision"] if r else 0,
            }
            if value["repair_executor"] == "native_patch":
                value["repair_executor"] = "codex"
                value["enabled"] = False
            return value

    def configure(self, owner, raw):
        require(
            isinstance(raw, dict)
            and {*DEFAULTS, "revision"} <= set(raw) <= {*DEFAULTS, "revision", *LEGACY_FIELDS}
        )
        value = {k: raw[k] for k in DEFAULTS}
        require(type(value["enabled"]) is bool)
        require(value["repair_executor"] == "codex", "RSI_CODEX_REQUIRED")
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
        fields = {"enabled", "model_seconds", "max_attempts", "observation_days", "revision"}
        require(isinstance(raw, dict) and {"revision"} <= set(raw) <= fields | LEGACY_FIELDS)
        value = self.configure(
            owner, {**self.settings(owner), **{k: v for k, v in raw.items() if k in fields}}
        )
        return {k: v for k, v in value.items() if k in fields}
